"""State-free repository marker detection.

This module deliberately returns string labels rather than importing
``RepositoryType``: the context owns that public enum and composes the verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from skillsaw.discovery import CONVENTIONAL_SKILL_DIRS, exact_name_exists
from skillsaw.formats.promptfoo import is_promptfoo_config
from skillsaw.paths import safe_resolve
from skillsaw.utils import read_yaml

WALK_SKIP_DIRS = frozenset(
    {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache"}
)

# Directories holding code this repository did not author. Their editor
# configuration belongs to whoever vendored it, and reporting on it would
# turn a green CI run red on upgrade over a file the maintainer cannot fix.
# Override with ``content-paths`` to lint a vendored tree deliberately.
VENDOR_DIR_NAMES = frozenset(
    {"vendor", "vendored", "third_party", "thirdparty", "bower_components"}
)

# Editor-owned directories whose contents ship in a repository. Cursor,
# Copilot/VS Code and Cline all read these from the nearest enclosing
# folder as well as the repository root, so a monorepo package can carry
# its own set — hence a walk rather than a root-anchored lookup.
AGENT_TOOL_DIR_NAMES = frozenset({".cursor", ".clinerules", ".github", ".vscode"})


@dataclass
class RepositoryScan:
    """Everything one filesystem walk of the repository yields.

    Discovery walks are the dominant cost of building a context on a large
    checkout, so the instruction-file sweep and the editor-directory sweep
    share a single pass instead of one each.
    """

    instruction_files: Tuple[Path, ...]
    tool_dirs: Dict[str, Tuple[Path, ...]]
    legacy_editor_files: Dict[str, Tuple[Path, ...]]


#: Pre-directory instruction files, read from the nearest enclosing directory
#: just as the matching `.cursor/` and `.clinerules/` directories are. `.clinerules`
#: is both a file and a directory name depending on the convention in use, and
#: the walk separates them by which listing they appear in. Collecting only the
#: root copy left a package's rules out of the tree entirely, and out of tool
#: detection with them.
LEGACY_EDITOR_FILES = (".cursorrules", ".clinerules")


def scan_repository(root: Path, root_names: Iterable[str]) -> RepositoryScan:
    """Walk *root* once, collecting instruction files and editor directories."""
    found = [root / name for name in root_names if (root / name).exists()]
    tool_dirs: Dict[str, List[Path]] = {name: [] for name in AGENT_TOOL_DIR_NAMES}
    legacy_editor: Dict[str, List[Path]] = {name: [] for name in LEGACY_EDITOR_FILES}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in WALK_SKIP_DIRS]
        here = Path(dirpath)
        found.extend(here / name for name in filenames if name.endswith(".instructions.md"))
        vendored = bool(VENDOR_DIR_NAMES.intersection(here.relative_to(root).parts))
        # The root copy has always been attached; a nested one is a new
        # claim, so it follows the tool-directory rule rather than the
        # instruction-file one and stays out of vendored trees.
        for legacy_name in LEGACY_EDITOR_FILES:
            if legacy_name in filenames and (here == root or not vendored):
                legacy_editor[legacy_name].append(here / legacy_name)
        for name in dirnames:
            # Instruction files keep the historical behaviour — the sweep
            # above already collected them — but a tool directory is a new
            # claim, so vendored trees stay out of it.
            if name in AGENT_TOOL_DIR_NAMES and not vendored:
                tool_dirs[name].append(here / name)
    return RepositoryScan(
        instruction_files=tuple(sorted(found)),
        tool_dirs={name: tuple(sorted(paths)) for name, paths in tool_dirs.items()},
        legacy_editor_files={name: tuple(sorted(paths)) for name, paths in legacy_editor.items()},
    )


#: Per-editor evidence inside a discovered tool directory. Any one of these
#: means the tool is configured here, so a repository whose only Cursor
#: artifact is ``hooks.json`` still activates the Cursor rules.
_EDITOR_EVIDENCE = {
    "HAS_CURSOR": (
        ".cursor",
        (
            ("rules", True),
            ("commands", True),
            ("skills", True),
            ("mcp.json", False),
            ("hooks.json", False),
        ),
    ),
    # ``.vscode`` is walked for attachment but contributes no format label:
    # the only thing skillsaw reads there is ``mcp.json``, and the MCP rules
    # are ungated, so there is no format-gated rule left looking at nothing.
    "HAS_COPILOT": (
        ".github",
        (
            ("copilot-instructions.md", False),
            ("instructions", True),
            ("prompts", True),
            ("agents", True),
            ("chatmodes", True),
            ("skills", True),
        ),
    ),
}


def instruction_formats(
    root: Path,
    files: Iterable[Path],
    is_excluded: Callable[[Path], bool],
    tool_dirs: Optional[Mapping[str, Iterable[Path]]] = None,
    legacy_editor_files: Optional[Mapping[str, Iterable[Path]]] = None,
) -> Set[str]:
    """Return instruction-format evidence labels from non-excluded markers.

    Detection reads the same walk that drives attachment. A tool directory
    found in a monorepo subpackage is evidence just as the root one is —
    otherwise the lint tree grows blocks that no format-gated rule ever
    looks at, which is the silent-no-op this linter exists to catch.
    """

    def marker(*parts: str, is_dir: bool = False) -> bool:
        """Test one non-excluded repository marker."""
        path = root.joinpath(*parts)
        if is_excluded(path):
            return False
        return path.is_dir() if is_dir else path.exists()

    dirs: Mapping[str, Iterable[Path]] = tool_dirs or {}

    def editor_marker(label: str) -> bool:
        """Whether any discovered directory holds this editor's evidence."""
        dir_name, entries = _EDITOR_EVIDENCE[label]
        candidates = list(dirs.get(dir_name) or ())
        if not candidates:
            candidates = [root / dir_name]
        for base in candidates:
            if is_excluded(base):
                continue
            for name, is_dir in entries:
                path = base / name
                if is_excluded(path):
                    continue
                if path.is_dir() if is_dir else path.exists():
                    return True
        return False

    def legacy_cursor() -> bool:
        """Any non-excluded `.cursorrules`, at the root or in a subpackage.

        Reads the same walk attachment reads, so detection and attachment
        cannot disagree about a nested one.
        """
        paths = (legacy_editor_files or {}).get(".cursorrules", ())
        return any(not is_excluded(path) for path in paths)

    def cline_marker() -> bool:
        """``.clinerules`` is a file in the old convention, a directory in the new."""
        if any(
            not is_excluded(path) for path in (legacy_editor_files or {}).get(".clinerules", ())
        ):
            return True
        if marker(".clinerules"):
            return True
        return any(not is_excluded(path) for path in (dirs.get(".clinerules") or ()))

    found: Set[str] = set()
    checks = (
        ("HAS_CURSOR", editor_marker("HAS_CURSOR") or legacy_cursor()),
        (
            "HAS_COPILOT",
            editor_marker("HAS_COPILOT")
            or any(path.name.endswith(".instructions.md") for path in files),
        ),
        ("HAS_CLINE", cline_marker()),
        ("HAS_GEMINI", marker("GEMINI.md")),
        ("HAS_QWEN", marker("QWEN.md")),
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


def has_skill_md_recursive(
    root: Path,
    should_skip: Callable[[Path], bool],
    _visited: Optional[Set[Path]] = None,
) -> bool:
    """Return whether a recursive, guarded walk finds an Agent Skill."""
    if _visited is None:
        _visited = set()
    resolved_root = safe_resolve(root)
    if resolved_root is None or resolved_root in _visited:
        return False
    _visited.add(resolved_root)
    try:
        for item in root.iterdir():
            if should_skip(item):
                continue
            if exact_name_exists(item, "SKILL.md"):
                return True
            if item.is_dir() and has_skill_md_recursive(item, should_skip, _visited):
                return True
    except OSError:
        pass
    return False


def is_agentskills_repo(root: Path, should_skip: Callable[[Path], bool]) -> bool:
    """Return whether the repository contains an Agent Skill entrypoint."""
    if exact_name_exists(root, "SKILL.md"):
        return True
    for rel in CONVENTIONAL_SKILL_DIRS:
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
