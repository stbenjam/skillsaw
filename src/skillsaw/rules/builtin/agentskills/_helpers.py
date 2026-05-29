"""Shared constants and helpers for agentskills rules"""

import json
import re
import threading
from pathlib import Path

NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
COMPATIBILITY_MAX_LENGTH = 500
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
CONSECUTIVE_HYPHENS = re.compile(r"--")
DEFAULT_ALLOWED_DIRS = {"scripts", "references", "assets", "evals"}

RENAMES_MANIFEST = ".skillsaw-renames.json"
_RENAMES_LOCK = threading.Lock()


def _to_kebab(name: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1-\2", name)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _read_renames_manifest(root: Path) -> list[dict]:
    path = root / RENAMES_MANIFEST
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        renames = data.get("renames", [])
        if isinstance(renames, list):
            return [
                r
                for r in renames
                if isinstance(r, dict)
                and isinstance(r.get("old"), str)
                and isinstance(r.get("new"), str)
            ]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _write_renames_manifest(root: Path, renames: list[dict]) -> None:
    path = root / RENAMES_MANIFEST
    if not renames:
        if path.exists():
            path.unlink()
        return
    path.write_text(
        json.dumps({"renames": renames}, indent=2) + "\n",
        encoding="utf-8",
    )


def _add_rename(root: Path, old: str, new: str) -> None:
    with _RENAMES_LOCK:
        renames = _read_renames_manifest(root)
        renames = [r for r in renames if r["old"] != old]
        renames.append({"old": old, "new": new})
        _write_renames_manifest(root, renames)
