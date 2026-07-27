"""Shared constants and helpers for agentskills rules"""

import json
import re
import threading
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from skillsaw.context import RepositoryType
from skillsaw.formats.codex import safe_resolve

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime
    from skillsaw.context import RepositoryContext

# Repository types whose lint tree can hold Agent Skills. One set shared by
# every rule in this package so a newly supported host cannot be wired into
# some of them and forgotten in the rest. CODEX_PLUGIN belongs here because
# a Codex plugin ships ``skills/<name>/SKILL.md`` in the same format — most
# visibly for a plugin installed under ``.codex/plugins/``, which no other
# repository type covers.
SKILL_REPO_TYPES = {
    RepositoryType.AGENTSKILLS,
    RepositoryType.SINGLE_PLUGIN,
    RepositoryType.MARKETPLACE,
    RepositoryType.DOT_CLAUDE,
    RepositoryType.CODEX_PLUGIN,
    # For the same reason MARKETPLACE is here: a catalog repository holds
    # the plugins, and their skills are discovered whether or not the
    # CODEX_PLUGIN type was also inferred.
    RepositoryType.CODEX_MARKETPLACE,
}

NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
COMPATIBILITY_MAX_LENGTH = 500
# Spec: lowercase alphanumerics and hyphens, must not start or end with a
# hyphen — digit-leading names like "3d-printing" are valid.
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CONSECUTIVE_HYPHENS = re.compile(r"--")
DEFAULT_ALLOWED_DIRS = {"scripts", "references", "assets", "evals"}

RENAMES_MANIFEST = ".skillsaw-renames.json"
_RENAMES_LOCK = threading.Lock()


def contained_skill_file(
    context: "RepositoryContext", skill_dir: Path, *parts: str
) -> Optional[Path]:
    """A file under *skill_dir*, or ``None`` when it escapes the plugin.

    Rules that read one of a skill's own documents — and in one case
    rewrite it — need the document to actually belong to the skill. A
    symlink pointing out of the owning Codex plugin makes the read, and any
    write, land outside the checkout, and lets an external file decide what
    the rule reports about files that are inside it. Skills belonging to no
    Codex plugin are unaffected.
    """
    candidate = skill_dir.joinpath(*parts)
    if not candidate.exists():
        return None
    root = context.codex_plugin_owning(skill_dir)
    if root is None:
        return candidate
    resolved = safe_resolve(candidate)
    if resolved is None or not resolved.is_relative_to(root):
        return None
    return candidate


def contained_eval_file(context: "RepositoryContext", skill_dir: Path) -> Optional[Path]:
    """``evals/evals.json`` for *skill_dir*, or ``None`` if it escapes."""
    return contained_skill_file(context, skill_dir, "evals", "evals.json")


def is_installed_plugin_skill(context: "RepositoryContext", path: Path) -> bool:
    """Whether *path* belongs to a plugin installed under ``.codex/plugins/``.

    The Codex manifest and structure rules stand down there because the
    repository did not author that content. Autofix has to follow the same
    line, and more strictly: rewriting a third-party ``SKILL.md`` edits a
    file the developer did not write and cannot meaningfully own, and the
    rename bookkeeping would record it in this repository. The checks still
    run — a hostile skill is still worth reporting — only the fix stands
    down.
    """
    if path is None:
        return False
    return context.is_codex_installed_plugin(path)


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
