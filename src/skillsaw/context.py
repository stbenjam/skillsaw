"""
Repository context detection and management
"""

from __future__ import annotations

import fnmatch
import functools
from enum import Enum
from pathlib import Path
from typing import Iterator, Optional, List, Dict, Any, Set, Tuple, TYPE_CHECKING
import json
import logging
import os

# Dependency-light format helper — safe to import at module top because it
# pulls in nothing from skillsaw (importing rules.builtin here would trigger
# that package's __init__ while ``context`` is still mid-import → cycle).
from .formats.codex import (
    CODEX_PLUGIN_MANIFEST as _CODEX_PLUGIN_MANIFEST,
    codex_declared_skill_dirs,
    codex_local_source_path,
    safe_exists,
    safe_is_dir,
    safe_is_symlink,
    safe_resolve,
)
from .formats.promptfoo import is_promptfoo_config
from .utils import read_json

if TYPE_CHECKING:
    from .lint_target import LintTarget

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _pattern_variants(pattern: str) -> Tuple[str, ...]:
    """Expand *pattern* into the fnmatch patterns it is tried as.

    :mod:`fnmatch` has no special handling for ``**`` — it behaves exactly
    like ``*`` (which already crosses ``/``) — so a leading ``**/`` demands
    at least one directory before the rest of the pattern and never matches
    at the start of a relative path: ``**/templates/**`` misses a top-level
    ``templates/``. To honor gitignore-style semantics where ``**/`` also
    matches zero leading directories, a variant with the ``**/`` prefix
    stripped is tried as well. A trailing ``/**`` also needs a variant
    without the suffix: fnmatch matches the directory's contents, but not
    the directory entry itself. Discovery often tests that entry before it
    reaches the contents. The original pattern is always kept, making the
    expansion a strict superset of plain fnmatch.
    """
    variants = {pattern}
    if pattern.startswith("**/"):
        variants.add(pattern[3:])
    for variant in tuple(variants):
        if variant.endswith("/**"):
            variants.add(variant[:-3])
    return tuple(sorted(variants))


def path_matches_patterns(path: Path, root: Path, patterns: List[str]) -> bool:
    """True if *path*, made relative to *root*, matches any fnmatch pattern.

    Patterns use :mod:`fnmatch` syntax where ``*`` crosses ``/``, extended
    with one gitignore-style rule via :func:`_pattern_variants`: a leading
    ``**/`` also matches at the start of the relative path, so
    ``**/templates/**`` excludes both a top-level ``templates/`` and a
    nested ``a/templates/``.

    The single exclusion predicate shared by the context, the lint tree, and
    the linter's per-rule excludes. *root* must be resolved; paths outside
    *root* never match.
    """
    if not patterns:
        return False
    try:
        rel = str(path.resolve().relative_to(root))
    except ValueError:
        return False
    return any(
        fnmatch.fnmatch(rel, variant) for pat in patterns for variant in _pattern_variants(pat)
    )


class RepositoryType(Enum):
    """Type of repository"""

    SINGLE_PLUGIN = "single-plugin"  # Single plugin at repo root
    MARKETPLACE = "marketplace"  # Marketplace with multiple plugins
    AGENTSKILLS = "agentskills"  # agentskills.io skill repo
    DOT_CLAUDE = "dot-claude"  # .claude/ directory with commands, skills, hooks, etc.
    CODERABBIT = "coderabbit"  # Repository with .coderabbit.yaml
    APM = "apm"  # Repository with .apm/ directory (Agent Package Manager)
    PROMPTFOO = "promptfoo"  # Repository with promptfoo eval configs
    CODEX_PLUGIN = "codex-plugin"  # OpenAI Codex plugin (.codex-plugin/plugin.json)
    CODEX_MARKETPLACE = "codex-marketplace"  # .agents/plugins/marketplace.json
    UNKNOWN = "unknown"  # Not a recognized repo type


HAS_CURSOR = "HAS_CURSOR"
HAS_COPILOT = "HAS_COPILOT"
HAS_GEMINI = "HAS_GEMINI"
HAS_AGENTS_MD = "HAS_AGENTS_MD"
HAS_KIRO = "HAS_KIRO"
HAS_CLAUDE_MD = "HAS_CLAUDE_MD"
HAS_CODERABBIT = "HAS_CODERABBIT"
ALL_INSTRUCTION_FORMATS = frozenset(
    {
        HAS_CURSOR,
        HAS_COPILOT,
        HAS_GEMINI,
        HAS_AGENTS_MD,
        HAS_KIRO,
        HAS_CLAUDE_MD,
        HAS_CODERABBIT,
    }
)


def _is_marketplace_filename(name: str) -> bool:
    """Whether *name* is a Codex catalog by name alone.

    A bare ``endswith`` also claims ``notamarketplace.json``, which then
    skips the duck-typing fallback and gets linted as a catalog on the
    strength of its spelling. ``openai/plugins`` splits its listing into
    ``api_marketplace.json``, so the qualifier is a real pattern — it just
    has to end at a separator.
    """
    lowered = name.lower()
    if lowered == "marketplace.json":
        return True
    return lowered.endswith("marketplace.json") and lowered[-17] in "-_."


def _read_json_or_none(path: Path) -> Any:
    """Parsed JSON at *path*, or ``None`` when absent or unparseable.

    Goes through the shared cached reader so a UTF-8 BOM is stripped and
    repeated reads of the same manifest cost nothing — discovery, the
    validity rule, and the registration rule all read these files.
    """
    data, error = read_json(path)
    return None if error else data


_CODEX_TYPES = {RepositoryType.CODEX_PLUGIN, RepositoryType.CODEX_MARKETPLACE}

# Distinguishes "not computed yet" from a computed ``None`` (the install
# directory does not resolve), which is a perfectly normal answer.
_UNSET = object()


class RepositoryContext:
    """
    Context information about the repository being linted

    Automatically detects repository type and gathers relevant metadata.
    """

    _INSTRUCTION_FILENAMES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

    _TYPE_PRIORITY = [
        RepositoryType.MARKETPLACE,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.APM,
        RepositoryType.DOT_CLAUDE,
        RepositoryType.AGENTSKILLS,
        RepositoryType.CODERABBIT,
        RepositoryType.PROMPTFOO,
        # Below the Claude equivalents: a repository that is both keeps its
        # Claude primary type, so existing output is unchanged. Listing them
        # at all is what stops a Codex-only repo from reporting ``unknown``
        # and drawing the CLI's "unrecognized repository" warning.
        RepositoryType.CODEX_MARKETPLACE,
        RepositoryType.CODEX_PLUGIN,
    ]

    # Compiled output directories that APM generates from .apm/ sources.
    # When .apm/ is present these are generated artifacts and should not be linted.
    APM_COMPILED_DIRS = frozenset((".claude", ".cursor", ".gemini", ".opencode", ".agents"))

    def __init__(
        self,
        root_path: Path,
        repo_types: Optional[Set[RepositoryType]] = None,
        exclude_patterns: Optional[List[str]] = None,
        content_paths: Optional[List[str]] = None,
    ):
        """
        Initialize repository context

        Args:
            root_path: Root directory of the repository
            repo_types: Optional explicit repository type override.
            exclude_patterns: Glob patterns (from config) filtering discovered
                plugins/skills/instruction files. Prefer passing them here so
                discovery results are filtered from the start, rather than
                mutating the attribute and calling :meth:`apply_excludes`.
            content_paths: Extra content glob patterns (from config) picked up
                by the lint tree.
        """
        self.root_path = root_path.resolve()
        self.content_paths: List[str] = list(content_paths) if content_paths else []
        self.exclude_patterns: List[str] = list(exclude_patterns) if exclude_patterns else []
        self.has_apm = self._detect_apm()
        self._apm_compiled_roots: Optional[Set[Path]] = None
        self._codex_marketplace_paths: Optional[List[Path]] = None
        self._codex_install_root: Any = _UNSET
        self._codex_roots: Optional[List[Path]] = None
        # An explicit --type override is a statement about what the caller
        # wants linted, not just which rules fire. Probing for Codex anyway
        # would attach its manifests, hooks, MCP files and skills to the
        # tree, where the generic rules would lint content the override was
        # meant to exclude. Detection, by contrast, has to probe first —
        # the Codex types are derived from what discovery finds.
        self._codex_discovery_enabled = (
            bool(_CODEX_TYPES & set(repo_types)) if repo_types is not None else True
        )
        # An explicit type is also the caller's statement that the format
        # *is* Codex, so the entrypoint is seeded even when the marker file
        # is missing. Otherwise ``--type codex-plugin`` on a repository
        # without ``.codex-plugin/`` would discover no plugin, create no
        # node, and report nothing — the requested check would never run.
        self._codex_plugin_forced = repo_types is not None and (
            RepositoryType.CODEX_PLUGIN in repo_types
        )
        self._codex_marketplace_forced = repo_types is not None and (
            RepositoryType.CODEX_MARKETPLACE in repo_types
        )
        self.codex_plugins: List[Path] = (
            self._discover_codex_plugins() if self._codex_discovery_enabled else []
        )
        self.repo_types: Set[RepositoryType] = (
            set(repo_types) if repo_types is not None else self._detect_types()
        )
        logger.info(
            "Detected repo types: %s", ", ".join(t.value for t in self.repo_types) or "none"
        )
        self.marketplace_data = self._load_marketplace() if self.has_marketplace() else None
        self.plugin_metadata: Dict[Path, Dict[str, Any]] = {}
        self.marketplace_entries: Dict[Path, Dict[str, Any]] = {}
        self.plugins = self._discover_plugins()
        self.skills: List[Path] = self._discover_skills()
        self.instruction_files: List[Path] = self._discover_instruction_files()
        self.detected_formats: Set[str] = set()
        # Plugin-contributed extension state, registered by the Linter after
        # plugin loading (see Linter._register_plugin_extensions):
        # detected custom repository type names, lint tree contributors as
        # (plugin name, callable) pairs, and errors raised by contributors
        # during tree construction (surfaced as violations by the Linter).
        self.plugin_repo_types: Set[str] = set()
        # Content globs contributed by detected plugin repo types. Kept
        # separate from ``content_paths`` (user config), which the Linter
        # overwrites on construction — a shared context must not lose
        # plugin contributions to that reset.
        self.plugin_content_paths: List[str] = []
        self.plugin_tree_contributors: List[tuple] = []
        self.plugin_extension_errors: List[str] = []
        # Set by skillsaw.plugins.register_extensions so repeated calls on a
        # shared context (e.g. two Linters over one context) are no-ops.
        self._plugin_extensions_registered = False
        self._lint_tree: Optional["LintTarget"] = None
        # Filters discovery results and computes detected_formats — excludes
        # must be applied before format detection so excluded files (e.g.
        # *.instructions.md under an excluded directory) don't flip format
        # flags like HAS_COPILOT.
        self.apply_excludes()

    @property
    def lint_tree(self) -> "LintTarget":
        if self._lint_tree is None:
            from .lint_tree import build_lint_tree

            self._lint_tree = build_lint_tree(self)
        return self._lint_tree

    def rebuild_lint_tree(self) -> None:
        self._lint_tree = None

    @property
    def repo_type(self) -> RepositoryType:
        """Primary repo type for backward compatibility."""
        for t in self._TYPE_PRIORITY:
            if t in self.repo_types:
                return t
        return RepositoryType.UNKNOWN

    def repo_type_names(self, include_unknown: bool = True) -> List[str]:
        """Sorted names of all detected repository types, builtin and plugin.

        ``unknown`` is a sentinel for "nothing detected"; when a plugin type
        matched, the repository *is* recognized, so the sentinel is dropped.
        """
        names = {t.value for t in self.repo_types}
        names.update(self.plugin_repo_types)
        if not include_unknown or len(names) > 1:
            names.discard(RepositoryType.UNKNOWN.value)
        return sorted(names)

    def is_path_excluded(self, path: Path) -> bool:
        """Check if a path matches any exclude pattern."""
        return path_matches_patterns(path, self.root_path, self.exclude_patterns)

    def apm_compiled_roots(self) -> Set[Path]:
        """Resolved compiled-output directories to skip when APM is present.

        APM compiles ``.apm/`` sources into these directories; the generated
        artifacts must not be linted or drive discovery. Computed once per
        context (the predicate runs in per-node discovery loops).
        """
        if self._apm_compiled_roots is None:
            roots: Set[Path] = set()
            if self.has_apm:
                for compiled_dir_name in self.APM_COMPILED_DIRS:
                    compiled_path = (self.root_path / compiled_dir_name).resolve()
                    if compiled_path.is_dir():
                        roots.add(compiled_path)
            self._apm_compiled_roots = roots
        return self._apm_compiled_roots

    def in_apm_compiled_dir(self, path: Path) -> bool:
        """Check if *path* is inside an APM compiled-output directory."""
        roots = self.apm_compiled_roots()
        if not roots:
            return False
        resolved = path.resolve()
        return any(resolved == root or resolved.is_relative_to(root) for root in roots)

    @staticmethod
    def _under_any(path: Path, roots: Set[Path]) -> bool:
        """Whether *path* resolves inside any of *roots*."""
        resolved = safe_resolve(path)
        if resolved is None:
            return False
        return any(resolved == r or resolved.is_relative_to(r) for r in roots)

    def apply_excludes(self) -> None:
        """Filter discovery results by exclude_patterns and refresh derived state.

        Filters plugins, skills, and instruction_files, then recomputes
        ``detected_formats`` and drops any cached lint tree so state derived
        from the (now filtered) lists cannot go stale. Called by the
        constructor; legacy callers that mutate ``exclude_patterns`` after
        construction must call it again. Filtering only narrows — previously
        excluded paths are not rediscovered.
        """
        if self.exclude_patterns:
            codex_before = list(self.codex_plugins)
            roots_before = {r for r in (safe_resolve(p) for p in codex_before) if r}
            marketplaces_before = tuple(self._codex_marketplace_paths or ())
            self.plugins = [p for p in self.plugins if not self.is_path_excluded(p)]
            self.codex_plugins = [p for p in self.codex_plugins if not self.is_path_excluded(p)]
            self.skills = [p for p in self.skills if not self.is_path_excluded(p)]
            self.instruction_files = [
                p for p in self.instruction_files if not self.is_path_excluded(p)
            ]
            codex_paths_changed = self.codex_plugins != codex_before
            codex_catalog_changed = any(self.is_path_excluded(path) for path in marketplaces_before)
            codex_set_changed = codex_paths_changed or codex_catalog_changed
            # Most excludes do not affect Codex discovery, so avoid probing
            # every plugin directory again. A newly excluded catalog is the
            # exception: it may be the only source for a plugin whose own path
            # does not match the exclusion.
            if codex_catalog_changed:
                self._codex_marketplace_paths = None
            if self._codex_discovery_enabled and codex_set_changed:
                self._codex_install_root = _UNSET
                self.codex_plugins = [
                    p for p in self._discover_codex_plugins() if not self.is_path_excluded(p)
                ]
            roots_after = {r for r in (safe_resolve(p) for p in self.codex_plugins) if r}
            dropped = roots_before - roots_after
            if dropped:
                # Skills were discovered from the old plugin set. A skill
                # under a plugin that just left it would otherwise stay in
                # ``skills`` and be attached as a standalone node, so the
                # generic skill and content rules would keep linting exactly
                # the vendor content the exclusion removed.
                # A dual-host plugin may leave the Codex set while remaining
                # an active Claude plugin. Its skills still have a surviving
                # owner and must not be pruned with Codex-only content.
                claude_roots = {r for r in (safe_resolve(p) for p in self.plugins) if r}
                self.skills = [
                    sk
                    for sk in self.skills
                    if not self._under_any(sk, dropped) or self._under_any(sk, claude_roots)
                ]
            if codex_set_changed:
                self._codex_roots = None
        self.detected_formats = self._detect_formats()
        self._lint_tree = None

    def _discover_instruction_files(self) -> List[Path]:
        """Discover instruction files at the repo root and named .instructions.md files.

        Finds:
        - Root-level AGENTS.md, CLAUDE.md, GEMINI.md
        - Any ``*.instructions.md`` files anywhere in the repo tree (Copilot
          named instruction files such as ``coding.instructions.md``)
        """
        files: List[Path] = [
            self.root_path / name
            for name in self._INSTRUCTION_FILENAMES
            if (self.root_path / name).exists()
        ]
        files.extend(self._find_named_instructions_md())
        return files

    def _find_named_instructions_md(self) -> List[Path]:
        """Walk the repo collecting ``*.instructions.md`` files, skipping heavy directories."""
        found: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            dirnames[:] = [d for d in dirnames if d not in self._WALK_SKIP_DIRS]
            for f in filenames:
                if f.endswith(".instructions.md"):
                    found.append(Path(dirpath) / f)
        return sorted(found)

    def _detect_formats(self) -> Set[str]:
        formats: Set[str] = set()

        def marker(*parts: str, is_dir: bool = False) -> bool:
            # Excluded marker files must not flip format flags — the lint
            # tree skips them, so format-gated rules would fire for nothing.
            p = self.root_path.joinpath(*parts)
            if self.is_path_excluded(p):
                return False
            return p.is_dir() if is_dir else p.exists()

        if marker(".cursor", "rules", is_dir=True) or marker(".cursorrules"):
            formats.add(HAS_CURSOR)
        if marker(".github", "copilot-instructions.md") or self._has_instructions_md():
            formats.add(HAS_COPILOT)
        if marker("GEMINI.md"):
            formats.add(HAS_GEMINI)
        if marker("AGENTS.md"):
            formats.add(HAS_AGENTS_MD)
        if marker(".kiro", is_dir=True):
            formats.add(HAS_KIRO)
        if marker("CLAUDE.md"):
            formats.add(HAS_CLAUDE_MD)
        if marker(".coderabbit.yaml"):
            formats.add(HAS_CODERABBIT)
        return formats

    _WALK_SKIP_DIRS = frozenset(
        {
            ".git",
            ".hg",
            ".svn",
            "node_modules",
            ".venv",
            "venv",
            "__pycache__",
            ".tox",
            ".mypy_cache",
        }
    )

    def _has_instructions_md(self) -> bool:
        """Check whether any ``*.instructions.md`` files were discovered."""
        return any(f.name.endswith(".instructions.md") for f in self.instruction_files)

    def _detect_apm(self) -> bool:
        """Check if this repository uses the APM (Agent Package Manager) format"""
        if (self.root_path / ".apm").is_dir():
            return True
        if (self.root_path / "apm.yml").is_file():
            return True
        return False

    def _detect_types(self) -> Set[RepositoryType]:
        """Detect all applicable repository types.

        A repository may match multiple types simultaneously (e.g. a marketplace
        that also has a .coderabbit.yaml).  SINGLE_PLUGIN and MARKETPLACE are
        mutually exclusive (elif chain), but everything else is independent.
        """
        types: Set[RepositoryType] = set()

        # Marketplace / single-plugin (mutually exclusive)
        if (self.root_path / ".claude-plugin" / "marketplace.json").exists():
            types.add(RepositoryType.MARKETPLACE)
        elif (self.root_path / ".claude-plugin").exists():
            types.add(RepositoryType.SINGLE_PLUGIN)
        elif self._has_legacy_claude_plugins_dir():
            types.add(RepositoryType.MARKETPLACE)

        # Agentskills
        if self._is_agentskills_repo():
            types.add(RepositoryType.AGENTSKILLS)

        # CodeRabbit
        if (self.root_path / ".coderabbit.yaml").exists():
            types.add(RepositoryType.CODERABBIT)

        # APM
        if self.has_apm:
            types.add(RepositoryType.APM)

        # DOT_CLAUDE
        if self._is_dot_claude():
            types.add(RepositoryType.DOT_CLAUDE)

        # Promptfoo
        if self._is_promptfoo_repo():
            types.add(RepositoryType.PROMPTFOO)

        # Codex — independent of the Claude types above. A repo commonly
        # ships both manifests side by side (skillsaw itself does), so these
        # must not be part of the mutually exclusive marketplace/plugin
        # chain.
        if self.has_codex_marketplace():
            types.add(RepositoryType.CODEX_MARKETPLACE)
        if self.codex_plugins:
            types.add(RepositoryType.CODEX_PLUGIN)

        if not types:
            types.add(RepositoryType.UNKNOWN)

        return types

    def _is_agentskills_repo(self) -> bool:
        """Check if this looks like an agentskills.io skill repository"""
        if (self.root_path / "SKILL.md").exists():
            return True

        # Standard discovery paths (checked explicitly since they start with dot)
        for discovery_path in (
            ".apm/skills",
            ".claude/skills",
            ".github/skills",
            ".agents/skills",
        ):
            skills_path = self.root_path / discovery_path
            if skills_path.is_dir() and self._has_skill_md_recursive(skills_path):
                return True

        # Recurse into non-dot subdirectories looking for SKILL.md
        return self._has_skill_md_recursive(self.root_path)

    def _is_legacy_claude_plugin_candidate(self, item: Path) -> bool:
        """Whether a ``plugins/`` child carries Claude provenance.

        ``commands/`` is a legacy Claude marker, but it is not evidence of
        Claude when Codex explicitly claims that directory. An explicit
        ``.claude-plugin`` marker still makes a dual-host plugin.
        """
        resolved = safe_resolve(item)
        if resolved is None or not resolved.is_relative_to(self.root_path):
            return False
        if (item / ".claude-plugin").exists():
            return True
        if not (item / "commands").exists():
            return False
        claims = [*self.codex_plugins, *self._codex_local_sources()]
        return all(safe_resolve(claim) != resolved for claim in claims)

    def _has_legacy_claude_plugins_dir(self) -> bool:
        plugins_dir = self.root_path / "plugins"
        if not plugins_dir.is_dir():
            return False
        try:
            return any(
                item.is_dir()
                and not item.name.startswith(".")
                and self._is_legacy_claude_plugin_candidate(item)
                for item in plugins_dir.iterdir()
            )
        except OSError:
            return False

    def _is_dot_claude(self) -> bool:
        """Check if this is a .claude/ directory or a repo containing one.

        When APM is present, .claude/ is a compiled output directory and should
        not drive repo type detection.
        """
        if self.has_apm:
            return False
        claude_dir = self.root_path
        if self.root_path.name != ".claude":
            claude_dir = self.root_path / ".claude"
        if not claude_dir.is_dir():
            return False
        markers = ("commands", "skills", "hooks", "agents", "rules")
        return any((claude_dir / m).is_dir() for m in markers)

    def _is_promptfoo_repo(self) -> bool:
        """Check if this repository contains promptfoo eval configs."""
        for f in self._walk_files(self.root_path):
            if fnmatch.fnmatch(f.name, "promptfooconfig*.yaml") or fnmatch.fnmatch(
                f.name, "promptfooconfig*.yml"
            ):
                return True
        evals_dir = self.root_path / "evals"
        if evals_dir.is_dir():
            from .utils import read_yaml

            for yaml_file in self._walk_files(evals_dir):
                if yaml_file.suffix not in (".yaml", ".yml"):
                    continue
                data, error = read_yaml(yaml_file)
                if not error and is_promptfoo_config(data):
                    return True
        return False

    def _walk_files(self, root: Path) -> Iterator[Path]:
        """Yield all files under *root*, pruning ``_WALK_SKIP_DIRS`` directories."""
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self._WALK_SKIP_DIRS]
            for f in filenames:
                yield Path(dirpath) / f

    def _should_skip_dir(self, item: Path) -> bool:
        """True if *item* is not a directory worth recursing into."""
        return not item.is_dir() or item.name.startswith(".") or item.name in self._WALK_SKIP_DIRS

    def _has_skill_md_recursive(self, path: Path) -> bool:
        """Check if any subdirectory contains SKILL.md, recursively"""
        try:
            for item in path.iterdir():
                if self._should_skip_dir(item):
                    continue
                if (item / "SKILL.md").exists():
                    return True
                if self._has_skill_md_recursive(item):
                    return True
        except OSError:
            pass
        return False

    def has_marketplace(self) -> bool:
        """Check if repository has a marketplace"""
        return (self.root_path / ".claude-plugin" / "marketplace.json").exists()

    # Codex reads a repo marketplace from ``.agents/plugins/marketplace.json``
    # and a plugin manifest from ``<plugin>/.codex-plugin/plugin.json``.
    # It also accepts ``.claude-plugin/marketplace.json`` for backward
    # compatibility, but skillsaw leaves that path to the Claude rules —
    # the schemas differ (Codex drops ``owner`` and adds ``policy``,
    # ``category`` and ``interface``), so validating one file against both
    # would report contradictory violations.
    CODEX_MARKETPLACE_DIR = (".agents", "plugins")
    CODEX_MARKETPLACE_FILENAME = "marketplace.json"
    # Re-exported from formats.codex so existing ``context.CODEX_PLUGIN_MANIFEST``
    # readers keep working; the definition lives with the readers that use it.
    CODEX_PLUGIN_MANIFEST = _CODEX_PLUGIN_MANIFEST
    # Where Codex installs plugins a developer added to their own checkout,
    # as opposed to plugins the repository authors.
    CODEX_INSTALL_DIR = (".codex", "plugins")

    def codex_marketplace_path(self) -> Path:
        """Path the Codex repo marketplace manifest would live at."""
        return self.root_path.joinpath(*self.CODEX_MARKETPLACE_DIR, self.CODEX_MARKETPLACE_FILENAME)

    def has_codex_marketplace(self) -> bool:
        """Check if repository has a Codex marketplace manifest.

        Existence, not parseability — a marketplace with broken JSON must
        still activate the Codex rules so they can report it.
        """
        return bool(self._discover_codex_marketplaces())

    def _discover_codex_marketplaces(self) -> List[Path]:
        """Codex marketplace manifests in ``.agents/plugins/``.

        ``marketplace.json`` is the documented path and is always taken on
        existence alone, so broken JSON still reaches the rules. A sibling
        *named* like a catalog — openai/plugins ships a second one as
        ``api_marketplace.json`` — is taken on existence for the same
        reason: dropping it because its JSON is broken, or because
        ``plugins`` is not an array, hides exactly the defect
        codex-marketplace-json-valid exists to report, and where there is
        no primary ``marketplace.json`` it disables Codex marketplace
        detection outright. Any other ``*.json`` still has to duck-type as
        a marketplace, because the directory is not reserved and unrelated
        JSON must not be linted as a catalog.
        """
        if self._codex_marketplace_paths is not None:
            return self._codex_marketplace_paths
        if not self._codex_discovery_enabled:
            self._codex_marketplace_paths = []
            return self._codex_marketplace_paths

        root = safe_resolve(self.root_path) or self.root_path

        def _inside(path: Path) -> bool:
            # A catalog that resolves outside the checkout is not this
            # repository's to read — and codex-marketplace-registration
            # writes the catalog back when it registers a plugin, so
            # following a symlink out would overwrite an external file.
            resolved = safe_resolve(path)
            return resolved is not None and resolved.is_relative_to(root)

        def _keep(path: Path) -> bool:
            # Exclusions are applied here rather than at each reader: the
            # lint tree filters them, but ``skillsaw docs`` reads this list
            # directly, so an excluded catalog would otherwise still supply
            # published pages and the generated title.
            return _inside(path) and not self.is_path_excluded(path)

        found: List[Path] = []
        primary = self.codex_marketplace_path()
        # Existence, not is_file(): a directory in place of the reserved
        # entrypoint is unusable, and it has to stay discovered for
        # codex-marketplace-json-valid to say so.
        # ``is_symlink()`` as well as ``exists()``: a dangling in-repository
        # symlink is an unusable catalog, and dropping it would declassify
        # the repository rather than let the rule report it — the same
        # reasoning plugin discovery applies to a missing manifest.
        if (safe_exists(primary) or safe_is_symlink(primary)) and _keep(primary):
            found.append(primary)

        primary_resolved = safe_resolve(primary)
        marketplace_dir = self.root_path.joinpath(*self.CODEX_MARKETPLACE_DIR)
        if safe_is_dir(marketplace_dir):
            try:
                siblings = sorted(marketplace_dir.glob("*.json"))
            except OSError:
                siblings = []
            for candidate in siblings:
                # Resolved comparison, not ``candidate == primary``: on a
                # case-insensitive filesystem ``MARKETPLACE.JSON`` is the
                # primary under a different spelling, and a path-equality
                # test would list the same file twice.
                candidate_resolved = safe_resolve(candidate)
                if candidate_resolved is not None and candidate_resolved == primary_resolved:
                    continue
                if not _keep(candidate):
                    continue
                if _is_marketplace_filename(candidate.name):
                    found.append(candidate)
                    continue
                data = _read_json_or_none(candidate)
                if isinstance(data, dict) and isinstance(data.get("plugins"), list):
                    found.append(candidate)

        if not found and self._codex_marketplace_forced and _keep(primary):
            # ``_keep``, not a bare exclusion check: it also enforces
            # containment. The registration rule writes this file back when
            # it registers a plugin, so seeding an unchecked path would let
            # ``fix --suggest`` rewrite a file outside the checkout through
            # a symlinked catalog. An explicit --type says what format the
            # repository is, not that its entrypoint may be anywhere.
            found.append(primary)

        self._codex_marketplace_paths = found
        return found

    def codex_catalog_exists(self) -> bool:
        """Whether any Codex catalog file is present in the checkout.

        Deliberately independent of ``_codex_discovery_enabled``: this
        answers "is this repository's catalog a Codex one", which the
        Claude rules need in order to stand down, and an explicit
        ``--type`` switches discovery off without changing the answer.
        Reading it from discovery would make ``--type marketplace`` restore
        the false positive the stand-down exists to remove.

        Every catalog counts, not just the primary ``marketplace.json`` —
        a repository whose only catalog is a sibling such as
        ``api_marketplace.json`` is no less a Codex marketplace.
        """
        root = safe_resolve(self.root_path)
        if root is None:
            return False

        def _usable(path: Path) -> bool:
            resolved = safe_resolve(path)
            if resolved is None or not resolved.is_relative_to(root):
                return False
            if self.is_path_excluded(path):
                return False
            return safe_exists(path) or safe_is_symlink(path)

        if _usable(self.codex_marketplace_path()):
            return True
        marketplace_dir = self.root_path.joinpath(*self.CODEX_MARKETPLACE_DIR)
        if not safe_is_dir(marketplace_dir):
            return False
        try:
            siblings = sorted(marketplace_dir.glob("*.json"))
        except OSError:
            return False
        for candidate in siblings:
            if not _usable(candidate):
                continue
            if _is_marketplace_filename(candidate.name):
                return True
            # The same duck-typing discovery applies to an arbitrarily named
            # sibling. Recognising fewer catalogs here than discovery does
            # leaves the Claude rule demanding a manifest for a repository
            # skillsaw has already classified as a Codex marketplace.
            data = _read_json_or_none(candidate)
            if isinstance(data, dict) and isinstance(data.get("plugins"), list):
                return True
        return False

    def codex_plugin_roots(self) -> List[Path]:
        """Resolved Codex plugin roots, computed once per context.

        ``codex_plugin_owning`` runs per skill inside agentskill-evals and
        agentskill-rename-refs, so resolving every root on each call costs
        roughly ``2 x skills x plugins`` filesystem round-trips on a large
        catalog.
        """
        if self._codex_roots is None:
            self._codex_roots = [
                r for r in (safe_resolve(p) for p in self.codex_plugins) if r is not None
            ]
        return self._codex_roots

    def codex_marketplace_paths(self) -> List[Path]:
        """Every discovered Codex marketplace manifest."""
        return list(self._discover_codex_marketplaces())

    def _discover_codex_plugins(self) -> List[Path]:
        """Discover directories holding a ``.codex-plugin/plugin.json`` manifest.

        Probes the documented layouts rather than walking the repository:
        the repo root (single-plugin repos), ``plugins/*`` (the layout the
        Codex docs prescribe for repo marketplaces), ``.codex/plugins/*``
        (the documented personal-install pattern), and every local source
        declared by the Codex marketplace. Explicit probes keep discovery
        O(entries) instead of adding a second whole-repo walk.

        The reserved ``.codex-plugin/`` directory is the evidence, not the
        manifest inside it. A directory whose ``plugin.json`` was deleted,
        misspelled, or replaced by a directory is still a Codex plugin with
        a broken entrypoint; dropping it here would take the repository's
        ``CODEX_PLUGIN`` type with it and leave the defect unreported.
        ``codex-plugin-json-valid`` reports the missing manifest.
        """
        found: List[Path] = []
        seen: Set[Path] = set()

        root = safe_resolve(self.root_path) or self.root_path

        def _contained(path: Path) -> Optional[Path]:
            resolved = safe_resolve(path)
            if resolved is None:
                return None
            return resolved if resolved == root or resolved.is_relative_to(root) else None

        def _add(directory: Path) -> None:
            # Both halves are checked, because either can be the symlink.
            # ``plugins/foo`` pointing out of the repository is the obvious
            # one; ``plugins/foo/.codex-plugin`` pointing out while ``foo``
            # itself is a real directory is the subtler one, and ``is_dir()``
            # follows it just the same. Either way skillsaw would read an
            # out-of-tree manifest — and codex-plugin-structure would list
            # the external directory's filenames under an in-repo path.
            resolved = _contained(directory)
            if resolved is None or resolved in seen:
                return
            # Contained within *this plugin*, not merely within the
            # repository: `plugins/a/.codex-plugin -> plugins/b/.codex-plugin`
            # stays in the checkout, so a repo-wide check accepts it and
            # plugin A is then discovered and documented using B's manifest.
            #
            # ``is_dir()`` is the wrong question for the first half: it is
            # false for a regular file named ``.codex-plugin`` and for a
            # dangling symlink, and both of those occupy the reserved name
            # just as surely as a directory does. Discarding them silently
            # un-types the repository, so a plugin whose manifest directory
            # was clobbered reports nothing at all. Existence — or a symlink
            # entry, which ``exists()`` denies when it dangles — keeps the
            # plugin; codex-plugin-json-valid then reports the unreadable
            # manifest.
            manifest_dir = directory / self.CODEX_PLUGIN_MANIFEST[0]
            if not (safe_exists(manifest_dir) or safe_is_symlink(manifest_dir)):
                return
            manifest_dir_resolved = safe_resolve(manifest_dir)
            if manifest_dir_resolved is None or not manifest_dir_resolved.is_relative_to(resolved):
                return
            # A missing manifest is still a plugin — codex-plugin-json-valid
            # reports it. One that resolves elsewhere is not.
            manifest = directory.joinpath(*self.CODEX_PLUGIN_MANIFEST)
            manifest_resolved = safe_resolve(manifest)
            if safe_exists(manifest) and (
                manifest_resolved is None or not manifest_resolved.is_relative_to(resolved)
            ):
                return
            seen.add(resolved)
            found.append(directory)

        _add(self.root_path)

        for parent in (
            self.root_path / "plugins",
            self.root_path.joinpath(*self.CODEX_INSTALL_DIR),
        ):
            if not parent.is_dir():
                continue
            try:
                entries = sorted(parent.iterdir())
            except OSError:
                continue
            for item in entries:
                if item.is_dir() and not item.name.startswith("."):
                    _add(item)

        for source in self._codex_local_sources():
            _add(source)

        if not found and self._codex_plugin_forced:
            # Only when the root has no marker at all. Discovery rejects a
            # ``.codex-plugin`` that resolves outside the checkout, and
            # seeding the root unconditionally would hand that rejected
            # marker straight back, and every rule would then read the
            # external manifest the containment gate exists to refuse.
            marker = self.root_path / self.CODEX_PLUGIN_MANIFEST[0]
            if not (safe_exists(marker) or safe_is_symlink(marker)) and _contained(self.root_path):
                found.append(self.root_path)

        return found

    def _codex_local_sources(self, marketplace_paths: Optional[List[Path]] = None) -> List[Path]:
        """Local plugin directories declared by the Codex marketplace.

        Codex resolves ``source.path`` against the *marketplace root* — the
        repository root — not against ``.agents/plugins/``. Sources that
        escape the root are dropped here; ``codex-marketplace-json-valid``
        reports them.

        ``marketplace_paths`` lets exclusion filtering compare the old and
        retained catalogs without rerunning whole-plugin discovery.
        """
        resolved: List[Path] = []
        catalogs = (
            marketplace_paths
            if marketplace_paths is not None
            else self._discover_codex_marketplaces()
        )
        for marketplace_file in catalogs:
            data = _read_json_or_none(marketplace_file)
            if not isinstance(data, dict):
                continue
            entries = data.get("plugins")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                path = codex_local_source_path(entry.get("source"))
                if path is None:
                    continue
                candidate = safe_resolve(self.root_path / path)
                if candidate is None:
                    continue  # codex-marketplace-json-valid reports the path
                if candidate == self.root_path or candidate.is_relative_to(self.root_path):
                    resolved.append(candidate)
        return resolved

    def codex_plugin_owning(self, path: Path) -> Optional[Path]:
        """The Codex plugin *path* sits in, nearest first, or ``None``.

        Nearest rather than first: a repository root that is itself a plugin
        contains the nested ones, so an outer match would let content escape
        the plugin that actually ships it.
        """
        resolved = safe_resolve(path)
        if resolved is None:
            return None
        owners = [
            r for r in self.codex_plugin_roots() if resolved == r or resolved.is_relative_to(r)
        ]
        return max(owners, key=lambda r: len(r.parts)) if owners else None

    def is_codex_installed_plugin(self, plugin_dir: Path) -> bool:
        """Whether *plugin_dir* is an installed plugin rather than an authored one.

        ``.codex/plugins/`` is the personal-install location — content a
        developer added to their own checkout. Its skills and hooks are
        still worth linting, but the repository's published catalog has no
        business listing it, so registration checks must skip it.
        """
        if self._codex_install_root is _UNSET:
            # Resolved once. This runs per SkillNode inside agentskill-name,
            # so re-resolving it per call is a filesystem round-trip for
            # every skill in the repository.
            self._codex_install_root = safe_resolve(
                self.root_path.joinpath(*self.CODEX_INSTALL_DIR)
            )
        install_root = self._codex_install_root
        if install_root is None:
            return False
        # Lexical first: ``.codex/plugins/foo`` symlinked to a plugin
        # elsewhere in the checkout resolves *out* of the install root, so a
        # resolved-only test would call it authored, then publish it and
        # let autofixes rewrite it. How it was reached is what makes it an
        # install, not where the bytes happen to live.
        lexical = self.root_path.joinpath(*self.CODEX_INSTALL_DIR)
        try:
            if plugin_dir != lexical and plugin_dir.is_relative_to(lexical):
                return True
        except ValueError:  # pragma: no cover - defensive
            pass
        resolved = safe_resolve(plugin_dir)
        if resolved is None:
            return False
        return resolved != install_root and resolved.is_relative_to(install_root)

    def _load_marketplace(self) -> Optional[Dict[str, Any]]:
        """Load marketplace.json if it exists"""
        marketplace_file = self.root_path / ".claude-plugin" / "marketplace.json"
        if not marketplace_file.exists():
            return None

        try:
            with open(marketplace_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def marketplace_plugin_root(self) -> Optional[str]:
        """
        Return metadata.pluginRoot from marketplace.json, if set

        Per the plugin-marketplaces spec, ``metadata.pluginRoot`` is a base
        directory prepended to relative plugin source paths (e.g.
        ``"./plugins"`` lets entries use ``"source": "formatter"`` instead
        of ``"./plugins/formatter"``).
        """
        if not self.marketplace_data:
            return None
        metadata = self.marketplace_data.get("metadata")
        if not isinstance(metadata, dict):
            return None
        plugin_root = metadata.get("pluginRoot")
        if isinstance(plugin_root, str) and plugin_root:
            return plugin_root
        return None

    def _resolve_plugin_source(self, source: Any, plugin_entry: Dict[str, Any]) -> Optional[Path]:
        """
        Resolve a plugin source from marketplace.json to a local path

        Handles relative paths (e.g., "./", "./custom/path") and remote sources
        (GitHub repos, git URLs). Remote sources are logged but skipped for local
        validation. Relative paths are resolved under metadata.pluginRoot when
        the marketplace declares one.

        Args:
            source: Plugin source (string path or dict with source type)
            plugin_entry: Full plugin entry for context (used for logging)

        Returns:
            Resolved Path if local and valid, None otherwise
        """
        plugin_name = plugin_entry.get("name", "unknown")

        # Handle relative path strings
        if isinstance(source, str):
            candidate = (self.root_path / source).resolve()
            plugin_root = self.marketplace_plugin_root()
            if plugin_root and not Path(source).is_absolute():
                # metadata.pluginRoot is prepended to relative sources (both
                # bare names and ./-prefixed paths). Real-world marketplaces
                # (e.g. jeremylongshore/claude-code-plugins-plus-skills) set
                # pluginRoot while their sources already include that prefix,
                # so prefer the spec composition but fall back to the
                # root-relative path when only the latter exists. The
                # containment check below still rejects any candidate that
                # escapes the repository, so a traversing pluginRoot cannot
                # smuggle a source outside the root.
                composed = (self.root_path / plugin_root / source).resolve()
                if safe_exists(composed) or not safe_exists(candidate):
                    candidate = composed

            # Disallow escaping the repo with .. paths
            try:
                candidate.relative_to(self.root_path)
            except ValueError:
                logger.warning(
                    "Plugin '%s' source '%s' escapes repository root. Skipping.",
                    plugin_name,
                    source,
                )
                return None

            if not safe_exists(candidate):
                logger.info(
                    "Plugin '%s' source '%s' not found locally. Skipping.", plugin_name, source
                )
                return None

            if not safe_is_dir(candidate):
                logger.info(
                    "Plugin '%s' source '%s' is not a directory. Skipping.", plugin_name, source
                )
                return None

            return candidate

        # Handle remote source objects (GitHub, git URLs)
        if isinstance(source, dict):
            source_type = source.get("source", "unknown")
            source_info = source.get("repo") or source.get("url", "unknown")
            logger.info(
                "Plugin '%s' uses remote source (%s: %s). Skipping local validation.",
                plugin_name,
                source_type,
                source_info,
            )
            return None

        # Unknown format
        logger.info("Plugin '%s' has unknown source format. Skipping.", plugin_name)
        return None

    def _is_valid_plugin_dir(
        self, path: Path, marketplace_entry: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Check if a directory is a valid plugin directory

        A directory is valid if it has plugin.json, standard component directories
        (commands, agents, skills, hooks), or if the marketplace entry has strict: false.

        Args:
            path: Directory path to check
            marketplace_entry: Optional marketplace entry for the plugin

        Returns:
            True if directory appears to be a valid plugin
        """
        # Check for plugin.json or standard component directories
        plugin_markers = [
            path / ".claude-plugin" / "plugin.json",
            path / "commands",
            path / "agents",
            path / "skills",
            path / "hooks",
        ]

        if any(marker.exists() for marker in plugin_markers):
            return True

        # When strict:false, plugin.json and component dirs can be absent
        if marketplace_entry is not None and marketplace_entry.get("strict", True) is False:
            return True

        return False

    def _discover_plugins(self) -> List[Path]:
        """
        Discover all plugin directories in the repository

        Handles three discovery methods:
        1. Single plugin at repository root
        2. Traditional plugins/ directory (backward compatibility)
        3. Marketplace.json-defined sources (flat structures, custom paths, remote)

        Multiple types can contribute plugins simultaneously.
        """
        plugins: List[Path] = []
        discovered_paths: Set[Path] = set()

        if RepositoryType.SINGLE_PLUGIN in self.repo_types:
            plugins.append(self.root_path)
            discovered_paths.add(self.root_path.resolve())

        if (
            RepositoryType.DOT_CLAUDE in self.repo_types
            and RepositoryType.MARKETPLACE not in self.repo_types
        ):
            claude_dir = (
                self.root_path if self.root_path.name == ".claude" else self.root_path / ".claude"
            )
            if claude_dir.resolve() not in discovered_paths:
                plugins.append(claude_dir)
                discovered_paths.add(claude_dir.resolve())

        if RepositoryType.MARKETPLACE in self.repo_types:
            # Discover from plugins/ directory (backward compatibility)
            self._discover_from_plugins_dir(plugins, discovered_paths)

            # Discover from marketplace.json plugin entries
            self._discover_from_marketplace(plugins, discovered_paths)

        return plugins

    def _discover_from_plugins_dir(self, plugins: List[Path], discovered_paths: Set[Path]) -> None:
        """Discover plugins from traditional plugins/ directory"""
        plugins_dir = self.root_path / "plugins"
        if not plugins_dir.is_dir():
            return

        for item in plugins_dir.iterdir():
            if not item.is_dir() or item.name.startswith("."):
                continue

            if not self._is_legacy_claude_plugin_candidate(item):
                continue

            resolved_path = item.resolve()
            if resolved_path not in discovered_paths:
                plugins.append(item)
                discovered_paths.add(resolved_path)

    def _discover_from_marketplace(self, plugins: List[Path], discovered_paths: Set[Path]) -> None:
        """Discover plugins from marketplace.json plugin entries"""
        if not self.marketplace_data or "plugins" not in self.marketplace_data:
            return

        marketplace_plugins = self.marketplace_data["plugins"]
        if not isinstance(marketplace_plugins, list):
            return

        for plugin_entry in marketplace_plugins:
            if not isinstance(plugin_entry, dict):
                continue
            source = plugin_entry.get("source")
            if not source:
                continue

            # Resolve source to local path (or skip if remote)
            plugin_path = self._resolve_plugin_source(source, plugin_entry)
            if not plugin_path:
                continue

            resolved_path = plugin_path.resolve()

            # Always store marketplace entry data for metadata merging
            self.marketplace_entries[resolved_path] = plugin_entry

            # Store metadata for strict: false plugins without plugin.json.
            # This must happen before the duplicate skip below so plugins the
            # plugins/ dir scan already discovered still get their metadata.
            is_strict = plugin_entry.get("strict", True)
            has_plugin_json = (plugin_path / ".claude-plugin" / "plugin.json").exists()

            if not is_strict and not has_plugin_json:
                self.plugin_metadata[resolved_path] = plugin_entry

            # Skip duplicates for plugin discovery
            if resolved_path in discovered_paths:
                continue

            # Validate plugin directory
            if not self._is_valid_plugin_dir(plugin_path, plugin_entry):
                continue

            plugins.append(plugin_path)
            discovered_paths.add(resolved_path)

    def get_plugin_name(self, plugin_path: Path) -> str:
        """
        Get the name of a plugin from its path

        Checks plugin.json first, falls back to marketplace metadata,
        then directory name.
        """
        resolved_path = plugin_path.resolve()

        # Try plugin.json. Non-string names (invalid, flagged by validation
        # rules) fall through to the directory-name fallback rather than
        # propagating a TypeError into rules that expect a string.
        plugin_json = plugin_path / ".claude-plugin" / "plugin.json"
        if plugin_json.exists():
            try:
                with open(plugin_json, "r") as f:
                    data = json.load(f)
                    # A malformed plugin.json can hold any JSON type, not
                    # just an object.
                    if isinstance(data, dict):
                        name = data.get("name")
                        if name and isinstance(name, str):
                            return name
            except (json.JSONDecodeError, IOError):
                pass

        # Try marketplace metadata
        if resolved_path in self.plugin_metadata:
            name = self.plugin_metadata[resolved_path].get("name", plugin_path.name)
            if isinstance(name, str):
                return name

        # Fall back to directory name
        return plugin_path.name

    def is_registered_in_marketplace(self, plugin_name: str) -> bool:
        """Check if a plugin is registered in marketplace.json"""
        if not self.marketplace_data or "plugins" not in self.marketplace_data:
            return False

        plugins = self.marketplace_data["plugins"]
        if not isinstance(plugins, list):
            return False

        return any(isinstance(p, dict) and p.get("name") == plugin_name for p in plugins)

    def get_plugin_metadata(self, plugin_path: Path) -> Optional[Dict[str, Any]]:
        """
        Get complete metadata for a plugin

        Returns metadata from plugin.json if present, otherwise falls back to
        marketplace entry data (for strict: false plugins without plugin.json).

        Args:
            plugin_path: Path to the plugin directory

        Returns:
            Dictionary with plugin metadata, or None if no metadata found
        """
        metadata = {}
        resolved_path = plugin_path.resolve()

        # Load from plugin.json if present
        plugin_json = plugin_path / ".claude-plugin" / "plugin.json"
        if plugin_json.exists():
            try:
                with open(plugin_json, "r") as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # Use marketplace metadata as fallback (for strict: false without plugin.json)
        if resolved_path in self.plugin_metadata:
            marketplace_entry = self.plugin_metadata[resolved_path]

            # Exclude marketplace-specific fields
            for key, value in marketplace_entry.items():
                if key not in ("source", "strict"):
                    metadata[key] = value

        # Merge marketplace entry fields that aren't already in metadata
        if resolved_path in self.marketplace_entries:
            entry = self.marketplace_entries[resolved_path]
            for key, value in entry.items():
                if key not in ("source", "strict") and key not in metadata:
                    metadata[key] = value

        return metadata or None

    def _discover_skills(self) -> List[Path]:
        """
        Discover agentskills.io skill directories.

        For AGENTSKILLS repos: root (single skill) or subdirs with SKILL.md.
        For plugin repos: skills from plugin_path/skills/*/.

        When APM is present, skills are discovered from .apm/skills/ and
        compiled output directories are excluded.
        """
        skills: List[Path] = []
        discovered: Set[Path] = set()

        if RepositoryType.AGENTSKILLS in self.repo_types:
            # Single skill at root
            if (self.root_path / "SKILL.md").exists():
                skills.append(self.root_path)
                discovered.add(self.root_path)
            else:
                # Skill collection: immediate subdirs with SKILL.md
                self._discover_skills_in_dir(self.root_path, skills, discovered)

            # Standard discovery paths (including APM)
            for discovery_path in (
                ".apm/skills",
                ".claude/skills",
                ".github/skills",
                ".agents/skills",
            ):
                skills_path = self.root_path / discovery_path
                if not skills_path.is_dir():
                    continue
                # Skip compiled output dirs when APM is present
                if self.in_apm_compiled_dir(skills_path):
                    continue
                self._discover_skills_in_dir(skills_path, skills, discovered)

        # For plugin repos, also discover embedded skills. Codex plugins are
        # included: an installed plugin under .codex/plugins/ lives in a
        # hidden directory the repository-wide scan never walks, so its
        # skills would otherwise never enter the lint tree.
        for plugin_path in self.plugins:
            skills_dir = plugin_path / "skills"
            if skills_dir.is_dir():
                self._discover_skills_in_dir(skills_dir, skills, discovered)

        for plugin_path in self.codex_plugins:
            plugin_root = safe_resolve(plugin_path)
            if plugin_root is None:
                continue
            # ``skills/`` is only the default. A manifest may point the field
            # somewhere else entirely, and for a hidden install that path is
            # the sole route into the tree.
            for skills_dir in (
                plugin_path / "skills",
                *codex_declared_skill_dirs(plugin_path),
            ):
                if not skills_dir.is_dir():
                    continue
                if (skills_dir / "SKILL.md").exists():
                    # A manifest may name one skill directly rather than a
                    # collection; descending would step straight past it.
                    resolved = safe_resolve(skills_dir)
                    entrypoint = safe_resolve(skills_dir / "SKILL.md")
                    if resolved is None or not resolved.is_relative_to(plugin_root):
                        continue
                    if entrypoint is None or not entrypoint.is_relative_to(plugin_root):
                        continue
                    if resolved not in discovered:
                        skills.append(skills_dir)
                        discovered.add(resolved)
                    continue
                self._discover_skills_in_dir(
                    skills_dir, skills, discovered, contain_within=plugin_root
                )

        return skills

    def _discover_skills_in_dir(
        self,
        parent: Path,
        skills: List[Path],
        discovered: Set[Path],
        contain_within: Optional[Path] = None,
        visited: Optional[Set[Path]] = None,
    ) -> None:
        """Discover skill directories within a parent directory, recursively.

        *contain_within* rejects children that resolve outside it. Passed
        for Codex plugins, where ``skills/external`` can be a symlink out
        of the repository and the SKILL.md behind it would otherwise be
        read as if the plugin shipped it. Left ``None`` on the call sites
        that predate Codex support, so their behaviour is unchanged.
        """
        # ``discovered`` only records directories that held a SKILL.md, so
        # it cannot stop a cycle: ``skills/a/loop -> ../..`` stays inside
        # the plugin, passes containment, and recurses until Python raises
        # RecursionError during context construction. ``visited`` records
        # every directory descended into, whether or not it held a skill.
        if visited is None:
            visited = set()
        try:
            for item in parent.iterdir():
                if self._should_skip_dir(item):
                    continue
                resolved = safe_resolve(item)
                if resolved is None or resolved in discovered or resolved in visited:
                    continue
                if contain_within is not None and not resolved.is_relative_to(contain_within):
                    continue
                entrypoint = safe_resolve(item / "SKILL.md")
                if entrypoint is not None and (item / "SKILL.md").exists():
                    # The directory being contained is not enough: SKILL.md
                    # can itself be a symlink out, and the tree follows it.
                    if contain_within is not None and not entrypoint.is_relative_to(contain_within):
                        continue
                    skills.append(item)
                    discovered.add(resolved)
                else:
                    visited.add(resolved)
                    self._discover_skills_in_dir(item, skills, discovered, contain_within, visited)
        except OSError:
            pass

    def __str__(self):
        """String representation of context"""
        return f"RepositoryContext(type={self.repo_type.value}, plugins={len(self.plugins)}, skills={len(self.skills)})"
