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
from skillsaw.discovery.excludes import is_root_or_ancestor_excluded
from skillsaw.formats.promptfoo import is_promptfoo_config
from skillsaw.formats import codex, devin, grok, muse
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
# Copilot/VS Code, Cline, Devin, OpenCode and Grok Build all read these from
# the nearest enclosing folder as well as the repository root, so a monorepo
# package can carry its own set — hence a walk rather than a root-anchored
# lookup.
AGENT_TOOL_DIR_NAMES = frozenset(
    {
        ".cursor",
        ".clinerules",
        ".github",
        ".vscode",
        ".opencode",
        codex.CODEX_DIR_NAME,
        grok.TOOL_DIR_NAME,
        muse.TOOL_DIR_NAME,
        *devin.TOOL_DIR_NAMES,
    }
)

# The tool directories whose nested ``skills/`` component is handed to the
# skill walk today. ``CONVENTIONAL_SKILL_DIRS`` names each one's
# root-relative spelling, which is where a single-package repository puts
# it; a monorepo package carries its own, and the generic skill walk never
# finds that one because it skips hidden directories. So the nested roots
# are handed over explicitly, from the walk that already located the
# directory. This is not every tool with a ``skills/`` spelling in that
# table — ``.cursor``, ``.github``, ``.clinerules`` and ``.opencode`` are
# not here yet, so a package's copy of those is still found only at the
# repository root.
#
# One tuple for both readers — ``marker_types`` below, which decides whether
# the repository is an Agent Skills repository at all, and
# ``RepositoryContext._discover_skills``, which passes them to
# ``discover_skills``. A name in only one of the two is a skill that is
# counted but never linted, or found but never counted.
NESTED_TOOL_SKILL_DIRS = (*devin.TOOL_DIR_NAMES, grok.TOOL_DIR_NAME)

# Reserved marker directories an *ecosystem* uses to declare a plugin or a
# catalog, as opposed to a tool's configuration directory above. Grok Build's
# ``.grok-plugin`` is here because a monorepo package can be a plugin or a
# marketplace of its own, and the one walk is what finds those without a
# second traversal. Recorded in the same ``tool_dirs`` mapping and read
# through ``agent_tool_dirs``; kept a separate name so the editor-tool
# vocabulary above keeps meaning editor tools.
PLUGIN_MARKER_DIR_NAMES = frozenset({grok.PLUGIN_DIR_NAME})

#: Every directory name the walk records, from both sets above.
SCANNED_DIR_NAMES = AGENT_TOOL_DIR_NAMES | PLUGIN_MARKER_DIR_NAMES


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
    tool_dirs: Dict[str, List[Path]] = {name: [] for name in SCANNED_DIR_NAMES}
    legacy_editor: Dict[str, List[Path]] = {name: [] for name in LEGACY_EDITOR_FILES}
    mcp_registry_files: List[Path] = []
    package_json_files: List[Path] = []
    skills_locks: List[Path] = []
    promptfoo_named: List[Path] = []
    promptfoo_evals: Dict[Path, List[Path]] = {}
    root_str = str(root)
    for dirpath, dirnames, filenames in os.walk(root_str):
        dirnames[:] = [name for name in dirnames if name not in WALK_SKIP_DIRS]
        here = Path(dirpath)
        # ``os.path.basename`` rather than ``here.name``: this runs once per
        # directory in the repository, and constructing the pathlib view of
        # every one of them to read a string costs more than the walk.
        if os.path.basename(dirpath) == muse.TOOL_DIR_NAME:
            # Muse's per-agent worktrees are whole checkouts of this
            # repository; walking them would attach every file twice.
            dirnames[:] = [name for name in dirnames if name not in muse.SCRATCH_DIR_NAMES]
        # Slice relative directory parts from dirpath to avoid repeatedly calling
        # Path.relative_to() for every directory and file during the walk.
        relative_dir = dirpath[len(root_str) :].lstrip(os.sep)
        dir_parts = tuple(relative_dir.split(os.sep)) if relative_dir else ()
        vendored = bool(VENDOR_DIR_NAMES.intersection(dir_parts))
        for name in filenames:
            path = here / name
            if fnmatch.fnmatch(name, "promptfooconfig*.yaml") or fnmatch.fnmatch(
                name, "promptfooconfig*.yml"
            ):
                promptfoo_named.append(path)
            if not (fnmatch.fnmatch(name, "*.yaml") or fnmatch.fnmatch(name, "*.yml")):
                continue
            relative_parts = dir_parts + (name,)
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
            if name in SCANNED_DIR_NAMES and not vendored:
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


#: Per-tool evidence inside a discovered tool directory, keyed by the
#: ``RepositoryType`` value it proves. Any one entry means the tool is
#: configured here, so a repository whose only Cursor artifact is
#: ``hooks.json`` still activates the Cursor rules.
_TOOL_EVIDENCE = {
    "cursor": (
        ".cursor",
        (
            ("rules", True),
            ("commands", True),
            ("skills", True),
            ("mcp.json", False),
            ("hooks.json", False),
        ),
    ),
    # ``.vscode`` is walked for attachment but contributes no repository
    # type: the only thing skillsaw reads there is ``mcp.json``, and the MCP
    # rules are ungated, so there is no gated rule left looking at nothing.
    "copilot": (
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
    # copy is a separate marker check in ``tool_types``.
    "opencode": (
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
    # ``hooks.json`` is the only committed file Muse reads from ``.muse/``;
    # ``worktrees/`` is child-agent scratch.
    "muse": (
        muse.TOOL_DIR_NAME,
        ((muse.HOOKS_FILENAME, False),),
    ),
    # Grok Build reads a whole project layer from ``.grok/``, and any one
    # piece of it is enough: the skills, rules, commands and agents load
    # unconditionally, while hooks and LSP additionally need folder trust.
    # The second group is listed even though nothing parses or attaches it
    # yet — a repository that configures only an MCP server through
    # ``.grok/config.toml``, or only a sandbox policy, is still a Grok
    # repository, and the summary should say so rather than ``unknown``.
    # Existence is the whole test for those, which is why adding one is a
    # line here and nothing else: with nothing attached there is no
    # attachment for detection to disagree with. ``plugins/`` is an install
    # location Grok's own plugin discovery owns, so it is deliberately not
    # evidence, and there is no ``.grok/mcp.json``: Grok reads project MCP
    # servers from ``config.toml`` and the repository-root ``.mcp.json``
    # only.
    "grok-project": (
        grok.TOOL_DIR_NAME,
        (
            (grok.RULES_DIR_NAME, True),
            (grok.SKILLS_DIR_NAME, True),
            (grok.AGENTS_DIR_NAME, True),
            (grok.COMMANDS_DIR_NAME, True),
            (grok.HOOKS_DIR_NAME, True),
            (grok.CONFIG_FILENAME, False),
            (grok.LSP_FILENAME, False),
            (grok.WORKFLOWS_DIR_NAME, True),
            (grok.ROLES_DIR_NAME, True),
            (grok.PERSONAS_DIR_NAME, True),
            (grok.SANDBOX_FILENAME, False),
        ),
    ),
    # ``hooks.json`` and ``config.toml`` are the committed project-layer
    # files skillsaw reads from ``.codex/``: Codex loads hooks from both and
    # merges them, and a config declares this project's MCP servers, so
    # either one alone is a Codex project. Existence is the whole test for
    # the config, as it is for Grok's.
    # ``.codex/plugins/`` is an install location — vendor-managed content
    # that Codex's own plugin discovery finds and that the Codex plugin
    # rules gate on repository type — so it is deliberately not evidence
    # here.
    "codex-project": (
        codex.CODEX_DIR_NAME,
        (
            (codex.CODEX_HOOKS_FILENAME, False),
            (codex.CODEX_CONFIG_FILENAME, False),
        ),
    ),
}


def tool_types(
    root: Path,
    files: Iterable[Path],
    is_excluded: Callable[[Path], bool],
    tool_dirs: Optional[Mapping[str, Iterable[Path]]] = None,
    legacy_editor_files: Optional[Mapping[str, Iterable[Path]]] = None,
    skills_lock_files: Optional[Iterable[Path]] = None,
) -> Set[str]:
    """Return ``RepositoryType`` values for the tools configured here.

    Values rather than enum members: discovery is state-free and imports
    nothing from ``context``, which owns the enum.

    Detection reads the same walk that drives attachment. A tool directory
    found in a monorepo subpackage is evidence just as the root one is —
    otherwise the lint tree grows blocks that no gated rule ever looks at,
    which is the silent-no-op this linter exists to catch.
    """

    def marker(*parts: str, is_dir: bool = False) -> bool:
        """Test one non-excluded repository marker."""
        path = root.joinpath(*parts)
        if is_excluded(path):
            return False
        return path.is_dir() if is_dir else path.exists()

    dirs: Mapping[str, Iterable[Path]] = tool_dirs or {}

    def tool_marker(type_value: str) -> bool:
        """Whether any discovered directory holds this tool's evidence."""
        dir_name, entries = _TOOL_EVIDENCE[type_value]
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
        ("cursor", tool_marker("cursor") or legacy_cursor()),
        (
            "copilot",
            tool_marker("copilot") or any(path.name.endswith(".instructions.md") for path in files),
        ),
        ("cline", cline_marker()),
        ("devin", devin_marker()),
        (
            "opencode",
            tool_marker("opencode")
            # OpenCode reads the project config from the repository root as
            # well as from ``.opencode/``, and a repository that configures
            # only a model and an MCP server has no ``.opencode/`` at all.
            or marker("opencode.json") or marker("opencode.jsonc"),
        ),
        # ``.muse/hooks.json`` is the only thing in a checkout that is Muse
        # Code's alone. Committed ``.agents/memory/`` notes are a shared
        # convention Muse reads — projects were committing them before Muse
        # shipped — so they are no more evidence of Muse than AGENTS.md is.
        ("muse", tool_marker("muse")),
        # Grok reads ``AGENTS.md`` and ``CLAUDE.md`` too, and both already
        # carry their own types, so ``.grok/`` itself is the only marker
        # that is Grok Build's alone.
        ("grok-project", tool_marker("grok-project")),
        ("codex-project", tool_marker("codex-project")),
        ("gemini", marker("GEMINI.md")),
        ("qwen", marker("QWEN.md")),
        (
            "agents-md",
            any(path.name == "AGENTS.md" and not is_excluded(path) for path in files),
        ),
        ("kiro", marker(".kiro", is_dir=True)),
        (
            "claude-md",
            any(path.name == "CLAUDE.md" and not is_excluded(path) for path in files),
        ),
        ("coderabbit", marker(".coderabbit.yaml")),
        (
            "skills-lock",
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
    is_excluded: Callable[[Path], bool] = lambda _: False,
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
        and not is_excluded(root / "SKILL.md")
        and not is_excluded(root)
    ):
        return True
    try:
        for item in root.iterdir():
            if should_skip(item) or is_excluded(item):
                continue
            if item.is_dir() and has_skill_md_recursive(
                item, should_skip, _visited, _boundary, is_excluded=is_excluded
            ):
                return True
    except OSError:
        pass
    return False


def is_agentskills_repo(
    root: Path,
    should_skip: Callable[[Path], bool],
    extra_skill_roots: Iterable[Path] = (),
    is_excluded: Callable[[Path], bool] = lambda _: False,
) -> bool:
    """Return whether the repository contains an Agent Skill entrypoint."""
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return False
    if (
        exact_name_exists(root, "SKILL.md")
        and contained_resolve(root / "SKILL.md", resolved_root) is not None
        and not is_excluded(root / "SKILL.md")
        and not is_excluded(root)
    ):
        return True
    for rel in CONVENTIONAL_SKILL_DIRS:
        path = root / rel
        if (
            contained_resolve(path, resolved_root) is not None
            and path.is_dir()
            and not is_root_or_ancestor_excluded(path, resolved_root, is_excluded)
            and has_skill_md_recursive(
                path, should_skip, _boundary=resolved_root, is_excluded=is_excluded
            )
        ):
            return True
    for path in extra_skill_roots:
        if (
            contained_resolve(path, resolved_root) is not None
            and path.is_dir()
            and not is_root_or_ancestor_excluded(path, resolved_root, is_excluded)
            and has_skill_md_recursive(
                path, should_skip, _boundary=resolved_root, is_excluded=is_excluded
            )
        ):
            return True
    return has_skill_md_recursive(
        root, should_skip, _boundary=resolved_root, is_excluded=is_excluded
    )


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
    is_excluded: Callable[[Path], bool] = lambda _: False,
) -> Set[str]:
    """Return independently detectable type labels (excluding ecosystems)."""
    found: Set[str] = set()
    resolved_root = safe_resolve(root)
    nested_skill_roots: List[Path] = []
    if resolved_root is not None:
        for name in NESTED_TOOL_SKILL_DIRS:
            for directory in (tool_dirs or {}).get(name, ()):
                skill_root = directory / "skills"
                resolved_skill_root = safe_resolve(skill_root)
                if resolved_skill_root is not None and resolved_skill_root.is_relative_to(
                    resolved_root
                ):
                    nested_skill_roots.append(skill_root)
    if is_agentskills_repo(root, should_skip, nested_skill_roots, is_excluded=is_excluded):
        found.add("agentskills")
    if apm:
        found.add("apm")
    if is_dot_claude(root, apm):
        found.add("dot-claude")
    if is_promptfoo_repo(root, promptfoo_named_files, promptfoo_eval_files):
        found.add("promptfoo")
    return found
