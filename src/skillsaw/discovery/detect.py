"""State-free repository marker detection.

This module deliberately returns string labels rather than importing
``RepositoryType``: the context owns that public enum and composes the verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from pathlib import Path
import os
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from skillsaw.discovery import CONVENTIONAL_SKILL_DIRS, exact_name_exists
from skillsaw.formats.promptfoo import is_promptfoo_config
from skillsaw.formats import devin
from skillsaw.paths import contained_resolve, safe_resolve
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
# Copilot/VS Code, Cline, Devin and OpenCode all read these from the nearest
# enclosing folder as well as the repository root, so a monorepo package can
# carry its own set — hence a walk rather than a root-anchored lookup.
AGENT_TOOL_DIR_NAMES = frozenset(
    {".cursor", ".clinerules", ".github", ".vscode", ".opencode", *devin.TOOL_DIR_NAMES}
)


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
    mcp_registry_files: Tuple[Path, ...]
    package_json_files: Tuple[Path, ...]
    skills_lock_files: Tuple[Path, ...]
    promptfoo_named_files: Tuple[Path, ...]
    promptfoo_eval_files: Dict[Path, Tuple[Path, ...]]


#: Pre-directory instruction files, read from the nearest enclosing directory
#: just as the matching `.cursor/` and `.clinerules/` directories are. `.clinerules`
#: is both a file and a directory name depending on the convention in use, and
#: the walk separates them by which listing they appear in. Collecting only the
#: root copy left a package's rules out of the tree entirely, and out of tool
#: detection with them.
LEGACY_EDITOR_FILES = (".cursorrules", ".clinerules")


def scan_repository(root: Path, root_names: Iterable[str]) -> RepositoryScan:
    """Walk *root* once, collecting instruction files and editor directories."""
    found = {root / name for name in root_names if (root / name).exists()}
    tool_dirs: Dict[str, List[Path]] = {name: [] for name in AGENT_TOOL_DIR_NAMES}
    legacy_editor: Dict[str, List[Path]] = {name: [] for name in LEGACY_EDITOR_FILES}
    mcp_registry_files: List[Path] = []
    package_json_files: List[Path] = []
    skills_locks: List[Path] = []
    promptfoo_named: List[Path] = []
    promptfoo_evals: Dict[Path, List[Path]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in WALK_SKIP_DIRS]
        here = Path(dirpath)
        vendored = bool(VENDOR_DIR_NAMES.intersection(here.relative_to(root).parts))
        for name in filenames:
            path = here / name
            if fnmatch.fnmatch(name, "promptfooconfig*.yaml") or fnmatch.fnmatch(
                name, "promptfooconfig*.yml"
            ):
                promptfoo_named.append(path)
            if not (fnmatch.fnmatch(name, "*.yaml") or fnmatch.fnmatch(name, "*.yml")):
                continue
            relative_parts = path.relative_to(root).parts
            for index, part in enumerate(relative_parts[:-1]):
                if os.path.normcase(part) == os.path.normcase("evals"):
                    evals_dir = root.joinpath(*relative_parts[: index + 1])
                    promptfoo_evals.setdefault(evals_dir, []).append(path)
        found.update(here / name for name in filenames if name.endswith(".instructions.md"))
        if not vendored:
            found.update(here / name for name in filenames if devin.is_instruction_filename(name))
            if "server.json" in filenames:
                mcp_registry_files.append(here / "server.json")
            if "package.json" in filenames:
                package_json_files.append(here / "package.json")
            if "skills-lock.json" in filenames:
                skills_locks.append(here / "skills-lock.json")
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
        mcp_registry_files=tuple(sorted(mcp_registry_files)),
        package_json_files=tuple(sorted(package_json_files)),
        skills_lock_files=tuple(sorted(skills_locks)),
        promptfoo_named_files=tuple(
            sorted(promptfoo_named, key=lambda path: (path.suffix == ".yml", path))
        ),
        promptfoo_eval_files={
            directory: tuple(sorted(paths, key=lambda path: (path.suffix == ".yml", path)))
            for directory, paths in promptfoo_evals.items()
        },
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
    # OpenCode 2.0 renamed every content directory to its plural, and still
    # loads the v1 singular. Both spellings are evidence: a repository
    # written for either version is an OpenCode repository, and a rule that
    # fired on only one of them would go quiet the day a project migrated.
    # ``opencode.json`` and ``opencode.jsonc`` inside ``.opencode/`` are
    # listed here; the root
    # copy is a separate marker check in ``instruction_formats``.
    "HAS_OPENCODE": (
        ".opencode",
        (
            ("opencode.json", False),
            ("opencode.jsonc", False),
            ("agents", True),
            ("agent", True),
            ("commands", True),
            ("command", True),
            ("modes", True),
            ("mode", True),
            ("skills", True),
            ("skill", True),
            # ``plugin(s)/`` holds JavaScript, which nothing attaches — but
            # it is still evidence that this directory is OpenCode's, and
            # ``opencode-config-valid`` reads the config file rather than
            # this directory. A repository whose only marker is a plugin
            # therefore turns the rule on and it finds the config, or finds
            # nothing and reports nothing.
            ("plugins", True),
            ("plugin", True),
        ),
    ),
}


def instruction_formats(
    root: Path,
    files: Iterable[Path],
    is_excluded: Callable[[Path], bool],
    tool_dirs: Optional[Mapping[str, Iterable[Path]]] = None,
    legacy_editor_files: Optional[Mapping[str, Iterable[Path]]] = None,
    skills_lock_files: Optional[Iterable[Path]] = None,
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

    def devin_marker() -> bool:
        """Whether Devin-specific rules, skills, or instructions are present."""
        resolved_root = safe_resolve(root)
        for dir_name in devin.TOOL_DIR_NAMES:
            candidates = list(dirs.get(dir_name) or ())
            if not candidates:
                candidates = [root / dir_name]
            for base in candidates:
                resolved_base = safe_resolve(base)
                if (
                    is_excluded(base)
                    or resolved_root is None
                    or resolved_base is None
                    or not resolved_base.is_relative_to(resolved_root)
                ):
                    continue
                for name, is_dir in (("rules", True), ("skills", True), ("global_rules.md", False)):
                    path = base / name
                    if is_excluded(path):
                        continue
                    if path.is_dir() if is_dir else path.exists():
                        return True
        return any(
            devin.is_devin_only_instruction_filename(path.name) and not is_excluded(path)
            for path in files
        )

    found: Set[str] = set()
    checks = (
        ("HAS_CURSOR", editor_marker("HAS_CURSOR") or legacy_cursor()),
        (
            "HAS_COPILOT",
            editor_marker("HAS_COPILOT")
            or any(path.name.endswith(".instructions.md") for path in files),
        ),
        ("HAS_CLINE", cline_marker()),
        ("HAS_DEVIN", devin_marker()),
        (
            "HAS_OPENCODE",
            editor_marker("HAS_OPENCODE")
            # OpenCode reads the project config from the repository root as
            # well as from ``.opencode/``, and a repository that configures
            # only a model and an MCP server has no ``.opencode/`` at all.
            or marker("opencode.json") or marker("opencode.jsonc"),
        ),
        ("HAS_GEMINI", marker("GEMINI.md")),
        ("HAS_QWEN", marker("QWEN.md")),
        (
            "HAS_AGENTS_MD",
            any(path.name.lower() == "agents.md" and not is_excluded(path) for path in files),
        ),
        ("HAS_KIRO", marker(".kiro", is_dir=True)),
        (
            "HAS_CLAUDE_MD",
            any(path.name == "CLAUDE.md" and not is_excluded(path) for path in files),
        ),
        ("HAS_CODERABBIT", marker(".coderabbit.yaml")),
        (
            "HAS_SKILLS_LOCK",
            any(not is_excluded(path) for path in (skills_lock_files or ())),
        ),
    )
    found.update(label for label, present in checks if present)
    return found


def should_skip_dir(item: Path) -> bool:
    """Whether *item* is not a directory worth recursing into."""
    return not item.is_dir() or item.name.startswith(".") or item.name in WALK_SKIP_DIRS


def has_apm(root: Path) -> bool:
    """Return whether the repository declares an APM project."""
    return (root / ".apm").is_dir() or (root / "apm.yml").is_file()


def has_skill_md_recursive(
    root: Path,
    should_skip: Callable[[Path], bool],
    _visited: Optional[Set[Path]] = None,
    _boundary: Optional[Path] = None,
) -> bool:
    """Return whether a contained recursive walk finds an Agent Skill."""
    if _visited is None:
        _visited = set()
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return False
    if _boundary is None:
        _boundary = resolved_root
    if not resolved_root.is_relative_to(_boundary) or resolved_root in _visited:
        return False
    _visited.add(resolved_root)
    if (
        exact_name_exists(root, "SKILL.md")
        and contained_resolve(root / "SKILL.md", _boundary) is not None
    ):
        return True
    try:
        for item in root.iterdir():
            if should_skip(item):
                continue
            if item.is_dir() and has_skill_md_recursive(item, should_skip, _visited, _boundary):
                return True
    except OSError:
        pass
    return False


def is_agentskills_repo(
    root: Path,
    should_skip: Callable[[Path], bool],
    extra_skill_roots: Iterable[Path] = (),
) -> bool:
    """Return whether the repository contains an Agent Skill entrypoint."""
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return False
    if (
        exact_name_exists(root, "SKILL.md")
        and contained_resolve(root / "SKILL.md", resolved_root) is not None
    ):
        return True
    for rel in CONVENTIONAL_SKILL_DIRS:
        path = root / rel
        if (
            contained_resolve(path, resolved_root) is not None
            and path.is_dir()
            and has_skill_md_recursive(path, should_skip, _boundary=resolved_root)
        ):
            return True
    for path in extra_skill_roots:
        if (
            contained_resolve(path, resolved_root) is not None
            and path.is_dir()
            and has_skill_md_recursive(path, should_skip, _boundary=resolved_root)
        ):
            return True
    return has_skill_md_recursive(root, should_skip, _boundary=resolved_root)


def is_dot_claude(root: Path, apm: bool) -> bool:
    """Return whether a source-owned ``.claude`` directory is present."""
    if apm:
        return False
    claude = root if root.name == ".claude" else root / ".claude"
    return claude.is_dir() and any(
        (claude / name).is_dir() for name in ("commands", "skills", "hooks", "agents", "rules")
    )


def is_promptfoo_repo(
    root: Path,
    named_files: Iterable[Path],
    eval_files: Mapping[Path, Iterable[Path]],
) -> bool:
    """Return whether repository files include a Promptfoo configuration."""
    if any(
        path.name.startswith("promptfooconfig") and path.suffix in (".yaml", ".yml")
        for path in named_files
    ):
        return True
    for path in eval_files.get(root / "evals", ()):
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
    promptfoo_named_files: Iterable[Path],
    promptfoo_eval_files: Mapping[Path, Iterable[Path]],
    tool_dirs: Optional[Mapping[str, Iterable[Path]]] = None,
) -> Set[str]:
    """Return independently detectable type labels (excluding ecosystems)."""
    found: Set[str] = set()
    resolved_root = safe_resolve(root)
    devin_skill_roots: List[Path] = []
    if resolved_root is not None:
        for name in devin.TOOL_DIR_NAMES:
            for directory in (tool_dirs or {}).get(name, ()):
                skill_root = directory / "skills"
                resolved_skill_root = safe_resolve(skill_root)
                if resolved_skill_root is not None and resolved_skill_root.is_relative_to(
                    resolved_root
                ):
                    devin_skill_roots.append(skill_root)
    if is_agentskills_repo(root, should_skip, devin_skill_roots):
        found.add("agentskills")
    if (root / ".coderabbit.yaml").exists():
        found.add("coderabbit")
    if apm:
        found.add("apm")
    if is_dot_claude(root, apm):
        found.add("dot-claude")
    if is_promptfoo_repo(root, promptfoo_named_files, promptfoo_eval_files):
        found.add("promptfoo")
    return found
