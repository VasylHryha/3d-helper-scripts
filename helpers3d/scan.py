"""Finds keys, private paths and your own deny-terms before they reach a commit."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, NamedTuple

from helpers3d.config import home_dir

KEY_PATTERNS = [
    ("Tripo key", re.compile(r"\btsk_[A-Za-z0-9_-]{16,}")),
    ("API key assignment", re.compile(r"""(?i)api[_-]?key["']?\s*[:=]\s*["'][^"'\s]{16,}["']""")),
    ("Bearer token", re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}")),
]
PATH_PATTERNS = [
    ("macOS/Linux home path", re.compile(r"(?<![\w.~])/(?:Users|home)/[A-Za-z0-9._-]+/")),
    ("Windows user path", re.compile(r"(?i)\b[A-Z]:\\+Users\\+[^\\\s]+")),
]
# Files that must describe the patterns above, so they are not scanned for paths.
PATH_EXEMPT = ("helpers3d/scan.py", "tests/test_scan.py")


class Finding(NamedTuple):
    path: str
    line: int
    what: str


def load_terms(root: Path) -> List[str]:
    terms: List[str] = []
    for source in (root / ".scan-terms", home_dir() / "scan-terms.txt"):
        if source.is_file():
            terms += [line.strip().lower() for line in source.read_text(encoding="utf-8").splitlines()
                      if line.strip() and not line.startswith("#")]
    return terms


def scan_text(path: str, text: str, terms: Iterable[str] = ()) -> List[Finding]:
    findings: List[Finding] = []
    check_paths = path.replace("\\", "/") not in PATH_EXEMPT
    patterns = KEY_PATTERNS + (PATH_PATTERNS if check_paths else [])
    for number, line in enumerate(text.splitlines(), 1):
        lowered = line.lower()
        for label, pattern in patterns:
            if pattern.search(line):
                findings.append(Finding(path, number, label))
        for term in terms:
            if term in lowered:
                findings.append(Finding(path, number, "deny-term %r" % term))
    return findings


def git_files(root: Path, staged: bool) -> List[str]:
    args = ["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=ACM"] if staged else \
           ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"]
    return [line for line in subprocess.run(args, capture_output=True, text=True, check=True).stdout.splitlines() if line]


def scan_repo(root: Path, staged: bool = False) -> List[Finding]:
    terms = load_terms(root)
    findings: List[Finding] = []
    for name in git_files(root, staged):
        try:
            if staged:  # what will be committed, not what is on disk now
                raw = subprocess.run(["git", "-C", str(root), "show", ":" + name], capture_output=True,
                                     check=True).stdout
                text = raw.decode("utf-8")
            else:
                text = (root / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError, subprocess.CalledProcessError):
            continue
        findings += scan_text(name, text, terms)
    return findings


def main(staged: bool, root: Path) -> int:
    findings = scan_repo(root, staged)
    for item in findings:
        print("%s:%d: %s" % item, file=sys.stderr)
    if findings:
        print("scan: %d finding(s). Remove them before committing." % len(findings), file=sys.stderr)
        return 1
    print("scan: clean")
    return 0
