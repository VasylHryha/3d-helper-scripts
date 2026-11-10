"""Find Blender on Windows, macOS or Linux and run a script in it with the same arguments everywhere."""
from __future__ import annotations

import glob as glob_module
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence


def scripts_dir() -> Path:
    return Path(__file__).resolve().parent / "blender_scripts"


def _version_key(path: str):
    return [int(part) for part in re.findall(r"\d+", path)]


def candidate_patterns(platform: str, env: Mapping[str, str], home: str) -> List[str]:
    if platform == "darwin":
        return ["/Applications/Blender*.app/Contents/MacOS/Blender",
                home + "/Applications/Blender*.app/Contents/MacOS/Blender"]
    if platform == "win32":
        roots = [env.get("ProgramFiles", r"C:\Program Files"),
                 env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 env.get("LOCALAPPDATA", "") + r"\Programs"]
        patterns = [root + r"\Blender Foundation\Blender*\blender.exe" for root in roots if root.strip("\\")]
        patterns.append(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
                        + r"\Steam\steamapps\common\Blender\blender.exe")
        return patterns
    return ["/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender",
            "/opt/blender*/blender", home + "/blender*/blender", home + "/.local/bin/blender"]


def find_blender(platform: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
                 home: Optional[str] = None, which: Callable[[str], Optional[str]] = shutil.which,
                 glob: Callable[[str], List[str]] = glob_module.glob) -> Optional[str]:
    """BLENDER_BIN wins, then the PATH, then the newest install in the usual places."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or str(Path.home())
    explicit = env.get("BLENDER_BIN")
    if explicit:
        if not Path(explicit).is_file():
            raise FileNotFoundError("BLENDER_BIN points to a file that does not exist: %s" % explicit)
        return explicit
    found = which("blender")
    if found:
        return found
    matches: List[str] = []
    for pattern in candidate_patterns(platform, env, home):
        matches.extend(glob(pattern))
    matches.sort(key=_version_key, reverse=True)
    return matches[0] if matches else None


def run_script(script: Path, args: Sequence[str] = (), blender: Optional[str] = None,
               timeout: Optional[float] = None) -> int:
    """Runs a script headless. The script gets `args` after a `--` and the factory settings, so a user's
    add-ons and preferences cannot change the result."""
    blender = blender or find_blender()
    if not blender:
        raise FileNotFoundError("Blender not found. Install it or set BLENDER_BIN to its executable.")
    # --python-exit-code makes a Python error in the script a non-zero exit instead of a silent 0.
    command = [blender, "--background", "--factory-startup", "--python-exit-code", "1",
               "--python", str(script), "--"] + [str(a) for a in args]
    return subprocess.run(command, timeout=timeout).returncode
