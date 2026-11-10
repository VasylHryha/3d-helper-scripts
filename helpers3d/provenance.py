"""One small record next to each asset: where it came from, what it cost, what licence applies."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_path(asset: Path) -> Path:
    return asset.with_name(asset.name + ".provenance.json")


def write_record(asset: Path, source: str, tool: str, license_note: str = "unspecified",
                 credits: Optional[int] = None, task_id: Optional[str] = None,
                 inputs: Optional[Dict[str, str]] = None, notes: str = "") -> Path:
    record = {
        "file": asset.name,
        "sha256": sha256_of(asset),
        "source": source,
        "tool": tool,
        "license": license_note,
        "credits": credits,
        "task_id": task_id,
        "inputs": inputs or {},
        "notes": notes,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path = record_path(asset)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_derived_record(source: Path, derived: Path, how: str) -> Path:
    """A converted file keeps the licence and origin of its source and records which exact file it came from."""
    old = {}
    if record_path(source).is_file():
        old = json.loads(record_path(source).read_text(encoding="utf-8"))
    path = write_record(derived, source=old.get("source", "unknown"), tool=old.get("tool", "unknown"),
                        license_note=old.get("license", "unspecified"), credits=old.get("credits"),
                        task_id=old.get("task_id"), inputs=old.get("inputs"),
                        notes="derived by %s from %s" % (how, source.name))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["derived_from"] = {"file": source.name, "sha256": sha256_of(source)}
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def verify_record(asset: Path) -> str:
    """Returns "ok", "missing" (no record) or "changed" (the file no longer matches its record)."""
    path = record_path(asset)
    if not path.is_file():
        return "missing"
    record = json.loads(path.read_text(encoding="utf-8"))
    return "ok" if record.get("sha256") == sha256_of(asset) else "changed"
