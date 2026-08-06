"""
Repository context detection and management
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Iterator, Optional, List, Dict, Any, Set, Tuple, TYPE_CHECKING
import logging
import os

# Safe to import at module top: discovery and formats.codex pull in nothing
# from skillsaw.context, so no import cycle while ``context`` is mid-import.
# ``merge_plugin_dirs`` and ``codex_local_source_path`` are re-exported here
# for callers that import them from ``skillsaw.context``.
from .discovery import merge_plugin_dirs
from .discovery import codex as codex_discovery
from .discovery import claude as claude_discovery
from .discovery import agent_plugins as agent_plugins_discovery
from .formats.codex import (
    CODEX_PLUGIN_MANIFEST as _CODEX_PLUGIN_MANIFEST,
    codex_local_source_path,  # noqa: F401 - compatibility re-export
)
from .discovery import detect as detect_discovery
from .discovery.excludes import pattern_variants as _pattern_variants
from .discovery.excludes import path_matches_patterns
from .paths import safe_is_dir, safe_resolve
from .repository_provenance import PluginProvenance, RepositoryProvenanceMixin

if TYPE_CHECKING:
    from .lint_target import LintTarget

logger = logging.getLogger(__name__)


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
    AGENT_PLUGIN = "agent-plugin"  # Portable Agent Plugins plugin.json
    UNKNOWN = "unknown"  # Not a recognized repo type


# Repository types whose lint tree can hold Agent Skills. One shared set so a
# newly supported host cannot be wired into some skill rules and forgotten in
# the rest. The Codex types belong here because Codex plugins ship
# ``skills/<name>/SKILL.md`` in the same format, and a catalog repository's
# plugin skills are discovered whether or not CODEX_PLUGIN was also inferred.
SKILL_REPO_TYPES = {
    RepositoryType.AGENTSKILLS,
    RepositoryType.SINGLE_PLUGIN,
    RepositoryType.MARKETPLACE,
    RepositoryType.DOT_CLAUDE,
    RepositoryType.CODEX_PLUGIN,
    RepositoryType.CODEX_MARKETPLACE,
    RepositoryType.AGENT_PLUGIN,
}


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


_CODEX_TYPES = {RepositoryType.CODEX_PLUGIN, RepositoryType.CODEX_MARKETPLACE}

# Distinguishes "not computed yet" from a computed ``None`` (the install
# directory does not resolve), which is a perfectly normal answer.
_UNSET = object()


class RepositoryContext(RepositoryProvenanceMixin):
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
        # Below the Claude equivalents, so a repository that is both keeps
        # its Claude primary type — but above the generic fallbacks: an
        # authored Codex plugin whose skills also match the Agent Skills
        # convention is a Codex plugin first, not an agentskills.io repo.
        RepositoryType.CODEX_MARKETPLACE,
        RepositoryType.CODEX_PLUGIN,
        RepositoryType.AGENT_PLUGIN,
        RepositoryType.AGENTSKILLS,
        RepositoryType.CODERABBIT,
        RepositoryType.PROMPTFOO,
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
        self.root_path = safe_resolve(root_path) or root_path
        self.content_paths: List[str] = list(content_paths) if content_paths else []
        self.exclude_patterns: List[str] = list(exclude_patterns) if exclude_patterns else []
        self._pattern_variants_cache: Dict[str, Tuple[str, ...]] = {}
        self.has_apm = self._detect_apm()
        self._apm_compiled_roots: Optional[Set[Path]] = None
        self._codex_marketplace_paths: Optional[List[Path]] = None
        self._codex_install_root: Any = _UNSET
        self._codex_roots: Optional[List[Path]] = None
        self._codex_claims: Optional[Set[Path]] = None
        self._codex_evidence: Optional[bool] = None
        self._agent_plugin_roots: Optional[Set[Path]] = None
        self._contained_plugin_roots: Optional[Set[Path]] = None
        self._agent_plugin_claims: Optional[Set[Path]] = None
        self._provenance_cache: Dict[Path, PluginProvenance] = {}
        # Views over _provenance_cache, invalidated with it: keeping them
        # beside it is what makes their lifetimes match the records they
        # summarise.
        self._format_scope_cache: Dict[Tuple[Path, str], bool] = {}
        # An explicit --type override gates *discovery* (which catalogs are
        # walked, which Codex rules activate), not *declaration*: the
        # provenance claim set stays --type-invariant, so a catalog-claimed
        # directory still gets its container and prose in the lint tree —
        # content and security rules read it, while Codex-format rules
        # remain repo-type-gated and quiet.
        self._codex_discovery_enabled = (
            bool(_CODEX_TYPES & set(repo_types)) if repo_types is not None else True
        )
        # A forced Codex type seeds the entrypoint even when the marker file
        # is missing — otherwise ``--type codex-plugin`` on a repository
        # without ``.codex-plugin/`` would discover no plugin, create no
        # node, and never run the requested check.
        self._codex_plugin_forced = repo_types is not None and (
            RepositoryType.CODEX_PLUGIN in repo_types
        )
        self._codex_marketplace_forced = repo_types is not None and (
            RepositoryType.CODEX_MARKETPLACE in repo_types
        )
        self._agent_plugin_discovery_enabled = (
            RepositoryType.AGENT_PLUGIN in set(repo_types) if repo_types is not None else True
        )
        self._agent_plugin_forced = repo_types is not None and (
            RepositoryType.AGENT_PLUGIN in repo_types
        )
        self.codex_plugins: List[Path] = (
            self._discover_codex_plugins() if self._codex_discovery_enabled else []
        )
        self.agent_plugins: List[Path] = (
            self._discover_agent_plugins() if self._agent_plugin_discovery_enabled else []
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
        # plugins/* children whose resolved location escapes the repository
        # root. Containment drops them from discovery (autofix must never
        # write outside the checkout), but the drop must stay visible:
        # marketplace-json-valid reads this list and files a violation for
        # each entry so an entire plugin cannot lose rule coverage silently.
        self.escaped_plugin_dirs: List[Path] = []
        self.plugins = self._discover_plugins()
        self.skills: List[Path] = self._discover_skills()
        self.instruction_files: List[Path] = self._discover_instruction_files()
        self.detected_formats: Set[str] = set()
        # Plugin-contributed extension state, registered by the Linter after
        # plugin loading (see Linter._register_plugin_extensions).
        self.plugin_repo_types: Set[str] = set()
        # Content globs contributed by detected plugin repo types. Kept
        # separate from ``content_paths`` (user config), which the Linter
        # overwrites on construction — a shared context must not lose
        # plugin contributions to that reset.
        self.plugin_content_paths: List[str] = []
        self.plugin_tree_contributors: List[tuple] = []
        self.plugin_extension_errors: List[str] = []
        # Fatal discovery problems that affect the repository itself rather
        # than a plugin. Linter surfaces these as repository-path-error
        # violations; direct tree/docs commands report them before output.
        self.lint_tree_errors: List[str] = []
        # Set by skillsaw.plugins.register_extensions so repeated calls on a
        # shared context (e.g. two Linters over one context) are no-ops.
        self._plugin_extensions_registered = False
        self._lint_tree: Optional["LintTarget"] = None
        # Excludes must be applied before format detection so excluded files
        # (e.g. *.instructions.md under an excluded directory) don't flip
        # format flags like HAS_COPILOT.
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
        return self.matches_patterns(path, self.exclude_patterns)

    def pattern_variants(self, pattern: str) -> Tuple[str, ...]:
        """Expand one pattern once for this repository context."""
        if pattern not in self._pattern_variants_cache:
            self._pattern_variants_cache[pattern] = _pattern_variants(pattern)
        return self._pattern_variants_cache[pattern]

    def matches_patterns(self, path: Path, patterns: List[str]) -> bool:
        """Match a path with pattern variants cached by this context."""
        return path_matches_patterns(path, self.root_path, patterns, self.pattern_variants)

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
                    compiled_path = self.root_path / compiled_dir_name
                    compiled_path = safe_resolve(compiled_path) or compiled_path
                    if compiled_path.is_dir():
                        roots.add(compiled_path)
            self._apm_compiled_roots = roots
        return self._apm_compiled_roots

    def in_apm_compiled_dir(self, path: Path) -> bool:
        """Check if *path* is inside an APM compiled-output directory."""
        roots = self.apm_compiled_roots()
        if not roots:
            return False
        resolved = safe_resolve(path) or path
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

        Called by the constructor; callers that mutate ``exclude_patterns``
        after construction must call it again. Filtering only narrows —
        previously excluded paths are not rediscovered.
        """
        if self.exclude_patterns:
            codex_before = list(self.codex_plugins)
            agent_plugins_before = list(self.agent_plugins)
            roots_before = {r for r in (safe_resolve(p) for p in codex_before) if r}
            marketplaces_before = tuple(self._codex_marketplace_paths or ())
            self.plugins = [p for p in self.plugins if not self.is_path_excluded(p)]
            self.codex_plugins = [p for p in self.codex_plugins if not self.is_path_excluded(p)]
            self.agent_plugins = [p for p in self.agent_plugins if not self.is_path_excluded(p)]
            self.skills = [p for p in self.skills if not self.is_path_excluded(p)]
            self.instruction_files = [
                p for p in self.instruction_files if not self.is_path_excluded(p)
            ]
            codex_paths_changed = self.codex_plugins != codex_before
            codex_catalog_changed = any(self.is_path_excluded(path) for path in marketplaces_before)
            codex_set_changed = codex_paths_changed or codex_catalog_changed
            # Re-probe only when needed: a newly excluded catalog may be the
            # only source for a plugin whose own path does not match the
            # exclusion.
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
                # Prune skills owned by plugins that just left the Codex set;
                # otherwise they attach as standalone nodes and keep linting
                # the very content the exclusion removed. Skills of a
                # dual-host plugin that remains an active Claude plugin still
                # have a surviving owner and must not be pruned.
                claude_roots = {r for r in (safe_resolve(p) for p in self.plugins) if r}
                self.skills = [
                    sk
                    for sk in self.skills
                    if not self._under_any(sk, dropped) or self._under_any(sk, claude_roots)
                ]
            if codex_set_changed:
                self._codex_roots = None
            if self.agent_plugins != agent_plugins_before:
                active_roots = {
                    root for p in self.agent_plugins if (root := safe_resolve(p)) is not None
                }
                dropped_roots = {
                    root
                    for p in agent_plugins_before
                    if (root := safe_resolve(p)) is not None and root not in active_roots
                }
                self.skills = [
                    skill for skill in self.skills if not self._under_any(skill, dropped_roots)
                ]
        # The claim set folds in both plugin roots and catalog sources, and
        # excludes can drop either — always recompute on the next consult.
        # The unconditional clear is also load-bearing for __init__ ordering:
        # type detection consults provenance before marketplace_entries
        # exists, and this end-of-init clear is what discards those early
        # records. Never scope it under ``if self.exclude_patterns:``.
        self._codex_claims = None
        self._codex_evidence = None
        self._agent_plugin_claims = None
        self._agent_plugin_roots = None
        self._contained_plugin_roots = None
        self._provenance_cache.clear()
        self._format_scope_cache.clear()
        self.detected_formats = self._detect_formats()
        self._lint_tree = None

    def _discover_instruction_files(self) -> List[Path]:
        """Discover instruction files at the repo root and named .instructions.md files.

        Finds:
        - Root-level AGENTS.md, CLAUDE.md, GEMINI.md
        - Any ``*.instructions.md`` files anywhere in the repo tree (Copilot
          named instruction files such as ``coding.instructions.md``)
        """
        return detect_discovery.instruction_files(self.root_path, self._INSTRUCTION_FILENAMES)

    def _detect_formats(self) -> Set[str]:
        return detect_discovery.instruction_formats(
            self.root_path, self.instruction_files, self.is_path_excluded
        )

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

    def _detect_apm(self) -> bool:
        """Check if this repository uses the APM (Agent Package Manager) format"""
        return detect_discovery.has_apm(self.root_path)

    def _detect_types(self) -> Set[RepositoryType]:
        """Detect all applicable repository types.

        A repository may match multiple types simultaneously (e.g. a marketplace
        that also has a .coderabbit.yaml).  SINGLE_PLUGIN and MARKETPLACE are
        mutually exclusive (elif chain), but everything else is independent.
        """
        types = {
            RepositoryType(label)
            for label in detect_discovery.marker_types(
                self.root_path,
                apm=self.has_apm,
                should_skip=self._should_skip_dir,
                walk_files=self._walk_files,
            )
        }

        # Marketplace / single-plugin (mutually exclusive)
        if (self.root_path / ".claude-plugin" / "marketplace.json").exists():
            types.add(RepositoryType.MARKETPLACE)
        elif (self.root_path / ".claude-plugin").exists():
            types.add(RepositoryType.SINGLE_PLUGIN)
        elif self._plugins_dir_suggests_claude_marketplace():
            types.add(RepositoryType.MARKETPLACE)

        # Codex — independent of the Claude types above. A repo commonly
        # ships both manifests side by side (skillsaw itself does), so these
        # must not be part of the mutually exclusive marketplace/plugin
        # chain.
        if self.has_codex_marketplace():
            types.add(RepositoryType.CODEX_MARKETPLACE)
        if self.codex_plugins:
            types.add(RepositoryType.CODEX_PLUGIN)
        if self.agent_plugins:
            types.add(RepositoryType.AGENT_PLUGIN)

        if not types:
            types.add(RepositoryType.UNKNOWN)

        return types

    def _plugins_dir_suggests_claude_marketplace(self) -> bool:
        """Whether ``plugins/`` is marketplace evidence once non-Claude claims
        are subtracted.

        A bare ``plugins/`` directory has always inferred MARKETPLACE. A
        Codex catalog explains the children it claims, so only a child it
        does not claim (or a dual-marker child) keeps that inference. A
        repository with no Codex evidence keeps its historical type exactly.
        """
        plugins_dir = self.root_path / "plugins"
        if not safe_is_dir(plugins_dir):
            return False
        try:
            children = [
                item
                for item in plugins_dir.iterdir()
                if item.is_dir() and not item.name.startswith(".")
            ]
        except OSError:
            return False
        if not children:
            # An empty plugins/ keeps its historical meaning unless another
            # ecosystem has positive evidence explaining the directory. A
            # portable Agent Plugins claim counts only when it lives under
            # plugins/ itself — a package declared at the repository root
            # says nothing about why plugins/ exists.
            resolved_plugins = safe_resolve(plugins_dir)
            agent_plugin_claims_plugins_dir = resolved_plugins is not None and any(
                claim.is_relative_to(resolved_plugins) for claim in self._agent_plugin_claim_set()
            )
            return not self.codex_catalog_exists() and not agent_plugin_claims_plugins_dir
        return any(
            not (provenance := self.provenance(item)).ecosystems or provenance.claude
            for item in children
        )

    def _walk_files(self, root: Path) -> Iterator[Path]:
        """Yield all files under *root*, pruning ``_WALK_SKIP_DIRS`` directories."""
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self._WALK_SKIP_DIRS]
            for f in filenames:
                yield Path(dirpath) / f

    def _should_skip_dir(self, item: Path) -> bool:
        """True if *item* is not a directory worth recursing into."""
        return not item.is_dir() or item.name.startswith(".") or item.name in self._WALK_SKIP_DIRS

    def has_marketplace(self) -> bool:
        """Check if repository has a marketplace"""
        return (self.root_path / ".claude-plugin" / "marketplace.json").exists()

    # Aliases for the discovery.codex and formats.codex definitions, one
    # import site for callers.
    CODEX_MARKETPLACE_DIR = codex_discovery.CODEX_MARKETPLACE_DIR
    CODEX_MARKETPLACE_FILENAME = codex_discovery.CODEX_MARKETPLACE_FILENAME
    CODEX_PLUGIN_MANIFEST = _CODEX_PLUGIN_MANIFEST
    CODEX_INSTALL_DIR = codex_discovery.CODEX_INSTALL_DIR

    def has_codex_marketplace(self) -> bool:
        """Check if repository has a Codex marketplace manifest.

        Existence, not parseability — a marketplace with broken JSON must
        still activate the Codex rules so they can report it.
        """
        return bool(self._discover_codex_marketplaces())

    def _discover_codex_marketplaces(self) -> List[Path]:
        """Discovery-side view of the one catalog enumerator: honors the
        ``--type`` gate, caches per context, and seeds the primary
        entrypoint when the type was forced.
        """
        if self._codex_marketplace_paths is None:
            if not self._codex_discovery_enabled:
                self._codex_marketplace_paths = []
            else:
                root = safe_resolve(self.root_path) or self.root_path
                self._codex_marketplace_paths = codex_discovery.enumerate_codex_catalogs(
                    self.root_path,
                    root,
                    self.is_path_excluded,
                    seed_forced_primary=self._codex_marketplace_forced,
                )
        return self._codex_marketplace_paths

    def _codex_catalog_files(self) -> List[Path]:
        """Codex catalog files present in the checkout, asked of the
        filesystem.

        Independent of ``_codex_discovery_enabled`` by design: the
        provenance claim set and ``codex_catalog_exists()`` read author
        *declarations*, which a ``--type`` override does not change —
        reading them from discovery would make ``--type marketplace``
        restore the false positives the stand-downs exist to remove.
        This declaration-side answer is never cached through the
        discovery slot.
        """
        resolved_root = safe_resolve(self.root_path)
        if resolved_root is None:
            return []
        return codex_discovery.enumerate_codex_catalogs(
            self.root_path, resolved_root, self.is_path_excluded
        )

    def codex_catalog_exists(self) -> bool:
        """Whether any Codex catalog file is present in the checkout."""
        return bool(self._codex_catalog_files())

    def codex_plugin_roots(self) -> List[Path]:
        """Resolved Codex plugin roots, computed once per context.

        ``codex_plugin_owning`` runs per skill, so resolving every root on
        each call would cost ~``skills x plugins`` filesystem round-trips.
        """
        if self._codex_roots is None:
            roots = {r for r in (safe_resolve(p) for p in self.codex_plugins) if r is not None}
            # Codex-exclusive catalog claims count as roots too: a
            # manifest-less claimed directory is a container in the lint
            # tree, and ownership questions (skill containment, docs
            # attribution) must see the same boundary — a claim-only
            # plugin falling out of the root set is exactly the
            # fell-between-paths class provenance exists to prevent.
            # Dual-identity claims stay out: their Claude manifest owns
            # them (docs deliberately refuse to publish a claim Codex
            # cannot install). The claim set is already resolved.
            roots |= {
                p
                for p in self._codex_claim_set()
                if not self.is_path_excluded(p) and self.provenance(p).codex_only
            }
            self._codex_roots = sorted(roots)
        return self._codex_roots

    def agent_plugin_roots(self) -> List[Path]:
        """Resolved portable package roots, independent of ``--type``.

        Discovery overrides decide which format rules run, not whether a
        package declaration remains a containment boundary for files a
        generic skill walk might otherwise follow.
        """
        return sorted(self._agent_plugin_root_set())

    def _agent_plugin_root_set(self) -> Set[Path]:
        """Cached set backing containment's per-skill ancestor lookups."""
        if self._agent_plugin_roots is None:
            roots = {
                resolved
                for path in self.agent_plugins
                if (resolved := safe_resolve(path)) is not None
            }
            roots.update(self._agent_plugin_claim_set())
            self._agent_plugin_roots = roots
        return self._agent_plugin_roots

    def distinct_plugin_dirs(self) -> List[Path]:
        """Every discovered plugin directory, deduplicated across ecosystems.

        The scan statistics count this rather than ``self.plugins``, which
        holds only Claude-style directories and reports zero for a
        manifest-only Codex catalog or a portable Agent Plugins collection.
        """
        return merge_plugin_dirs(self.plugins, self.codex_plugins, self.agent_plugins)

    def codex_marketplace_paths(self) -> List[Path]:
        """Every discovered Codex marketplace manifest."""
        return list(self._discover_codex_marketplaces())

    def _discover_codex_plugins(self) -> List[Path]:
        """Directories holding a Codex manifest, probed by the documented
        layouts (see :func:`skillsaw.discovery.codex.discover_codex_plugins`).
        """
        return codex_discovery.discover_codex_plugins(
            self.root_path,
            self._codex_local_sources(),
            forced=self._codex_plugin_forced,
        )

    def _discover_agent_plugins(self) -> List[Path]:
        """Portable packages declared at the root or under ``plugins/*``."""
        return [
            path
            for path in agent_plugins_discovery.discover_agent_plugins(
                self.root_path,
                forced=self._agent_plugin_forced,
            )
            if not self.is_path_excluded(path)
        ]

    def _agent_plugin_claim_set(self) -> Set[Path]:
        """Filesystem-declared portable plugin roots, independent of ``--type``."""
        if self._agent_plugin_claims is None:
            self._agent_plugin_claims = {
                resolved
                for path in agent_plugins_discovery.discover_agent_plugins(self.root_path)
                if not self.is_path_excluded(path) and (resolved := safe_resolve(path)) is not None
            }
        return self._agent_plugin_claims

    def _codex_local_sources(self) -> List[Path]:
        """Local plugin directories declared by the Codex marketplace."""
        # Filesystem-enumerated, not discovery-gated: these feed the
        # provenance claim set, which must be ``--type``-invariant.
        return codex_discovery.codex_local_sources(self.root_path, self._codex_catalog_files())

    def _codex_claims_possible(self) -> bool:
        """Whether any directory in this checkout could carry a Codex claim.

        Computed once per context. With no Codex evidence anywhere, a
        per-directory provenance consult can only ever answer "not Codex" —
        and the skill walk runs one for every directory it descends into,
        at ~6 syscalls each, on repositories that have no Codex content.

        Conservative when a ``--type`` override switched discovery off:
        provenance stays override-invariant, so a contained
        ``.codex-plugin`` still declares Codex even though nothing walked
        for it, and the per-directory consult has to run.
        """
        if self._codex_evidence is None:
            self._codex_evidence = not self._codex_discovery_enabled or bool(
                self._codex_claim_set()
            )
        return self._codex_evidence

    def _codex_claim_set(self) -> Set[Path]:
        """Every resolved directory Codex claims, computed once per context.

        The union of discovered plugin roots and the catalogs' local
        sources. Rebuilding it on each call would make repository detection
        quadratic in the catalog size.
        """
        if self._codex_claims is None:
            claims = {r for r in (safe_resolve(p) for p in self.codex_plugins) if r is not None}
            claims.update(self._codex_local_sources())
            self._codex_claims = claims
        return self._codex_claims

    def is_codex_installed_plugin(self, plugin_dir: Path) -> bool:
        """Whether *plugin_dir* is an installed plugin rather than an authored one.

        ``.codex/plugins/`` is the personal-install location — content a
        developer added to their own checkout. Its skills and hooks are
        still worth linting, but the repository's published catalog has no
        business listing it, so registration checks must skip it.
        """
        if self._codex_install_root is _UNSET:
            # Resolved once — this runs per SkillNode, so re-resolving per
            # call costs a filesystem round-trip for every skill.
            self._codex_install_root = codex_discovery.codex_install_root(self.root_path)
        return codex_discovery.is_installed_codex_plugin(
            plugin_dir, self.root_path, self._codex_install_root
        )

    def _load_marketplace(self) -> Optional[Dict[str, Any]]:
        """Load marketplace.json if it exists"""
        return claude_discovery.load_marketplace(self.root_path)

    def marketplace_plugin_root(self) -> Optional[str]:
        """
        Return metadata.pluginRoot from marketplace.json, if set

        Per the plugin-marketplaces spec, ``metadata.pluginRoot`` is a base
        directory prepended to relative plugin source paths (e.g.
        ``"./plugins"`` lets entries use ``"source": "formatter"`` instead
        of ``"./plugins/formatter"``).
        """
        return claude_discovery.marketplace_plugin_root(self.marketplace_data)

    def _resolve_plugin_source(self, source: Any, plugin_entry: Dict[str, Any]) -> Optional[Path]:
        """Resolve a Claude marketplace source through state-free discovery."""
        return claude_discovery.resolve_plugin_source(
            self.root_path, self.marketplace_data, source, plugin_entry
        )

    def _discover_plugins(self) -> List[Path]:
        """Discover Claude-compatible plugin directories without moving state."""
        result = claude_discovery.discover_plugins(
            self.root_path,
            single_plugin=RepositoryType.SINGLE_PLUGIN in self.repo_types,
            dot_claude=RepositoryType.DOT_CLAUDE in self.repo_types,
            marketplace=RepositoryType.MARKETPLACE in self.repo_types,
            codex_enabled=bool(_CODEX_TYPES & self.repo_types),
            marketplace_data=self.marketplace_data,
        )
        self.plugin_metadata.update(result.metadata)
        self.marketplace_entries.update(result.entries)
        self.escaped_plugin_dirs.extend(result.escaped)
        return result.paths

    def get_plugin_name(self, plugin_path: Path) -> str:
        """Return the manifest, marketplace, or directory plugin name."""
        return claude_discovery.plugin_name(plugin_path, self.plugin_metadata)

    def is_registered_in_marketplace(self, plugin_name: str) -> bool:
        """Check if a plugin is registered in marketplace.json"""
        if not self.marketplace_data or "plugins" not in self.marketplace_data:
            return False

        plugins = self.marketplace_data["plugins"]
        if not isinstance(plugins, list):
            return False

        return any(isinstance(p, dict) and p.get("name") == plugin_name for p in plugins)

    def get_plugin_metadata(self, plugin_path: Path) -> Optional[Dict[str, Any]]:
        """Return merged manifest and marketplace plugin metadata."""
        return claude_discovery.plugin_metadata(
            plugin_path, self.plugin_metadata, self.marketplace_entries
        )

    def _discover_skills(self) -> List[Path]:
        """Discover Agent Skills through the state-free Claude discovery seam."""
        recursive_agent_plugins = [
            plugin
            for plugin in self.agent_plugin_roots()
            if (provenance := self.provenance(plugin)).claude or provenance.codex
        ]
        return claude_discovery.discover_skills(
            self.root_path,
            agentskills=RepositoryType.AGENTSKILLS in self.repo_types,
            # A plugins/* layout can cause legacy Claude discovery to list an
            # Agent-only sibling. Only an actual Claude declaration permits
            # recursive Claude skill discovery for a portable package.
            plugins=[
                plugin
                for plugin in self.plugins
                if not self.provenance(plugin).agent_plugin or self.provenance(plugin).claude
            ],
            codex_plugins=self.codex_plugins,
            # Declaration-invariant roots keep portable skills visible under
            # an unrelated ``--type`` override while still enforcing their
            # fixed immediate-child discovery semantics.
            agent_plugins=self.agent_plugin_roots(),
            recursive_agent_plugins=recursive_agent_plugins,
            in_apm_compiled_dir=self.in_apm_compiled_dir,
            should_skip=self._should_skip_dir,
            claim_boundary=self._contained_plugin_claim_boundary,
            containment_claims_possible=self._contained_plugin_claims_possible,
            is_containment_plugin=self._is_containment_plugin,
        )

    def __str__(self):
        """String representation of context"""
        return (
            f"RepositoryContext(type={self.repo_type.value}, "
            f"plugins={len(self.distinct_plugin_dirs())}, skills={len(self.skills)})"
        )
