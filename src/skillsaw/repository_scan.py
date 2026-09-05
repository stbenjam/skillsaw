"""Cached stateful views over the repository's discovery walks."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set, TYPE_CHECKING, Tuple

from .discovery import claude as claude_discovery
from .discovery import detect as detect_discovery
from .repository_types import RepositoryType

if TYPE_CHECKING:
    from .discovery.detect import RepositoryScan
    from .repository_provenance import PluginProvenance


class RepositoryScanMixin:
    """Repository scan orchestration shared by format-specific mixins.

    Two walks live here: the single-pass repository scan the tool-directory
    and instruction-file lookups read, and skill discovery, which takes the
    ecosystems' plugin roots and ownership predicates from the host and
    returns the skill list every rule reads. Both are filesystem work rather
    than orchestration, which is why they sit beside each other here instead
    of in ``RepositoryContext``.
    """

    _INSTRUCTION_FILENAMES: Tuple[str, ...]

    if TYPE_CHECKING:
        root_path: Path
        instruction_files: List[Path]
        repo_types: Set[RepositoryType]
        plugins: List[Path]
        codex_plugins: List[Path]

        def grok_plugin_roots(self) -> List[Path]: ...

        antigravity_plugins: List[Path]

        def antigravity_plugin_roots(self) -> List[Path]: ...

        _scan: Optional[RepositoryScan]

        def is_path_excluded(self, path: Path) -> bool: ...

        def agent_plugin_roots(self) -> List[Path]: ...

        def provenance(self, plugin_dir: Path) -> PluginProvenance: ...

        def in_apm_compiled_dir(self, path: Path) -> bool: ...

        def _should_skip_dir(self, item: Path) -> bool: ...

        def _contained_plugin_claim_boundary(self, parent: Path) -> Optional[Path]: ...

        def _contained_plugin_claims_possible(self) -> bool: ...

        def _is_containment_plugin(self, path: Path) -> bool: ...

    def _discover_instruction_files(self) -> List[Path]:
        """Discover root and nested instruction files read by supported tools.

        Includes root conventions, Copilot ``*.instructions.md`` files, and
        Devin's documented names at nested project levels. The work shares
        one filesystem walk with :meth:`agent_tool_dirs`.
        """
        return list(self._repository_scan().instruction_files)

    def _repository_scan(self) -> RepositoryScan:
        """Return the cached single-pass walk of the repository."""
        if self._scan is None:
            self._scan = detect_discovery.scan_repository(
                self.root_path, self._INSTRUCTION_FILENAMES
            )
        return self._scan

    def agent_tool_dirs(self, name: str) -> List[Path]:
        """Return every non-excluded directory called *name* in the repository.

        Two kinds of caller, one walk. Editor tools — Cursor (``.cursor``),
        Copilot/VS Code (``.github``), Cline (``.clinerules``), Devin
        (``.devin``/``.windsurf``), OpenCode (``.opencode``) — read
        customizations from the nearest enclosing directory, so a monorepo
        package may carry its own alongside the root. Ecosystem markers
        (``.grok-plugin``) are the same shape of question: a plugin or a
        catalog in a package is found here rather than by a second
        traversal.
        """
        return [
            path
            for path in self._repository_scan().tool_dirs.get(name, ())
            if not self.is_path_excluded(path)
        ]

    def legacy_editor_files(self, name: str) -> List[Path]:
        """Every non-excluded *name* legacy editor file in the repository."""
        return [
            path
            for path in self._repository_scan().legacy_editor_files.get(name, ())
            if not self.is_path_excluded(path)
        ]

    def promptfoo_named_files(self) -> List[Path]:
        """Promptfoo conventionally named files from the shared repository walk."""
        return list(self._repository_scan().promptfoo_named_files)

    def promptfoo_eval_files(self, evals_dir: Path) -> List[Path]:
        """YAML candidates beneath one lexical ``evals/`` directory."""
        return list(self._repository_scan().promptfoo_eval_files.get(evals_dir, ()))

    def _detect_tool_type_values(self) -> set[str]:
        """``RepositoryType`` values for the tools this repository configures.

        Values rather than members: discovery stays state-free and imports
        nothing from ``context``, which owns the enum.
        """
        return detect_discovery.tool_types(
            self.root_path,
            self.instruction_files,
            self.is_path_excluded,
            self._repository_scan().tool_dirs,
            self._repository_scan().legacy_editor_files,
            self._repository_scan().skills_lock_files,
        )

    #: Alias for the one definition in discovery. Two copies of "which
    #: directories does a walk prune" are how a checkout starts being walked
    #: differently by two callers that both believe they agree.
    _WALK_SKIP_DIRS = detect_discovery.WALK_SKIP_DIRS

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
            # Config and catalog declarations retain custom skill paths
            # under unrelated --type overrides, just like their tree nodes.
            grok_plugins=self.grok_plugin_roots(),
            # The claim union, not the gated discovery list: a plugin a
            # ``plugins.json`` registry names has a container and its hooks
            # and MCP file either way, and its ``skills/`` must not vanish
            # because an unrelated ``--type`` switched generic Agent Skills
            # discovery off. Excluded roots are already dropped.
            antigravity_plugins=self.antigravity_plugin_roots(),
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
            # Devin/Windsurf, Grok Build and Antigravity each read the
            # nearest enclosing tool directory, so a monorepo package carries
            # its own ``skills/``. ``CONVENTIONAL_SKILL_DIRS`` covers only the
            # root-relative spelling and the generic walk skips hidden
            # directories, so the nested roots are handed over from the walk
            # that already found them — the same tuple detection reads.
            additional_skill_dirs=(
                directory / "skills"
                for name in detect_discovery.NESTED_TOOL_SKILL_DIRS
                for directory in self.agent_tool_dirs(name)
            ),
            is_excluded=self.is_path_excluded,
        )
