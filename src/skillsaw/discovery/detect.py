"""State-free repository marker detection.

This module deliberately returns string labels rather than importing
``RepositoryType``: the context owns that public enum and composes the verdict.
"""

from __future__ import annotations

from pathlib import Path
import os
from typing import Callable, Iterable, List, Set

from skillsaw.formats.promptfoo import is_promptfoo_config
from skillsaw.utils import read_yaml

WALK_SKIP_DIRS = frozenset(
    {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache"}
)


def instruction_files(root: Path, root_names: Iterable[str]) -> List[Path]:
    """Find root instruction files and named Copilot instructions."""
    found = [root / name for name in root_names if (root / name).exists()]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in WALK_SKIP_DIRS]
        found.extend(
            Path(dirpath) / name for name in filenames if name.endswith(".instructions.md")
        )
    return sorted(found)


def instruction_formats(
    root: Path, files: Iterable[Path], is_excluded: Callable[[Path], bool]
) -> Set[str]:
    """Return instruction-format evidence labels from non-excluded markers."""

    def marker(*parts: str, is_dir: bool = False) -> bool:
        """Test one non-excluded repository marker."""
        path = root.joinpath(*parts)
        if is_excluded(path):
            return False
        return path.is_dir() if is_dir else path.exists()

    found: Set[str] = set()
    checks = (
        ("HAS_CURSOR", marker(".cursor", "rules", is_dir=True) or marker(".cursorrules")),
        (
            "HAS_COPILOT",
            marker(".github", "copilot-instructions.md")
            or any(path.name.endswith(".instructions.md") for path in files),
        ),
        ("HAS_GEMINI", marker("GEMINI.md")),
        ("HAS_AGENTS_MD", marker("AGENTS.md")),
        ("HAS_KIRO", marker(".kiro", is_dir=True)),
        ("HAS_CLAUDE_MD", marker("CLAUDE.md")),
        ("HAS_CODERABBIT", marker(".coderabbit.yaml")),
    )
    found.update(label for label, present in checks if present)
    return found


def has_apm(root: Path) -> bool:
    """Return whether the repository declares an APM project."""
    return (root / ".apm").is_dir() or (root / "apm.yml").is_file()


def has_skill_md_recursive(root: Path, should_skip: Callable[[Path], bool]) -> bool:
    """Return whether a recursive, guarded walk finds an Agent Skill."""
    try:
        for item in root.iterdir():
            if should_skip(item):
                continue
            if (item / "SKILL.md").exists():
                return True
            if item.is_dir() and has_skill_md_recursive(item, should_skip):
                return True
    except OSError:
        pass
    return False


def is_agentskills_repo(root: Path, should_skip: Callable[[Path], bool]) -> bool:
    """Return whether the repository contains an Agent Skill entrypoint."""
    if (root / "SKILL.md").exists():
        return True
    for rel in (".apm/skills", ".claude/skills", ".github/skills", ".agents/skills"):
        path = root / rel
        if path.is_dir() and has_skill_md_recursive(path, should_skip):
            return True
    return has_skill_md_recursive(root, should_skip)


def is_dot_claude(root: Path, apm: bool) -> bool:
    """Return whether a source-owned ``.claude`` directory is present."""
    if apm:
        return False
    claude = root if root.name == ".claude" else root / ".claude"
    return claude.is_dir() and any(
        (claude / name).is_dir() for name in ("commands", "skills", "hooks", "agents", "rules")
    )


def is_promptfoo_repo(root: Path, walk_files: Callable[[Path], object]) -> bool:
    """Return whether repository files include a Promptfoo configuration."""
    if any(
        path.name.startswith("promptfooconfig") and path.suffix in (".yaml", ".yml")
        for path in walk_files(root)
    ):
        return True
    evals = root / "evals"
    if not evals.is_dir():
        return False
    for path in walk_files(evals):
        if path.suffix not in (".yaml", ".yml"):
            continue
        data, error = read_yaml(path)
        if not error and is_promptfoo_config(data):
            return True
    return False


def marker_types(
    root: Path,
    *,
    apm: bool,
    should_skip: Callable[[Path], bool],
    walk_files: Callable[[Path], object],
) -> Set[str]:
    """Return independently detectable type labels (excluding ecosystems)."""
    found: Set[str] = set()
    if is_agentskills_repo(root, should_skip):
        found.add("agentskills")
    if (root / ".coderabbit.yaml").exists():
        found.add("coderabbit")
    if apm:
        found.add("apm")
    if is_dot_claude(root, apm):
        found.add("dot-claude")
    if is_promptfoo_repo(root, walk_files):
        found.add("promptfoo")
    return found
