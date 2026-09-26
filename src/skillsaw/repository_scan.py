"""Cached stateful views over the repository's discovery walks."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set, TYPE_CHECKING, Tuple

from .discovery import claude as claude_discovery
from .discovery import detect as detect_discovery
from .formats.openclaw import MANIFEST
from .repository_types import RepositoryType, TOOL_REPO_TYPES
from .utils import read_json
from .paths import contained_resolve, safe_resolve

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
        _overridden_types: Optional[Set[RepositoryType]]
        exclude_patterns: List[str]
        _pi_packages_cache: Optional[Tuple[Tuple[str, ...], List[Path], Set[Path]]]
        plugins: List[Path]
        codex_plugins: List[Path]

        def openclaw_plugin_roots(self) -> List[Path]: ...

        def grok_plugin_roots(self) -> List[Path]: ...

        antigravity_plugins: List[Path]

        def antigravity_plugin_roots(self) -> List[Path]: ...

        _scan: Optional[RepositoryScan]

        def is_path_excluded(self, path: Path) -> bool: ...

        def agent_plugin_roots(self) -> List[Path]: ...

        def provenance(self, plugin_dir: Path) -> PluginProvenance: ...

        def resolve_path(self, path: Path) -> Optional[Path]: ...

        def in_apm_compiled_dir(self, path: Path) -> bool: ...

        def _should_skip_dir(self, item: Path) -> bool: ...

        def _contained_plugin_claim_boundary(self, parent: Path) -> Optional[Path]: ...

        def _contained_plugin_claims_possible(self) -> bool: ...

        def _is_containment_plugin(self, path: Path) -> bool: ...

    @property
    def skill_paths(self) -> List[Path]:
        """Display paths for portable and native skills.

        A directory-style skill is its directory in both dialects; only a
        flat Pi skill is reported as a file.
        """
        from .blocks.pi import PiSkillBlock

        return list(self.skills) + [
            b.path.parent if b.path.name == "SKILL.md" else b.path
            for b in self.lint_tree.find(PiSkillBlock)
        ]

    @property
    def skill_count(self) -> int:
        """Portable directories and Pi's native skills, including flat files."""
        return len(self.skill_paths)

    @property
    def _pi_package_forced(self) -> bool:
        """A forced type selects resources without changing provenance."""
        return RepositoryType.PI_PACKAGE in (getattr(self, "_overridden_types", None) or ())

    def pi_discovery_roots(self) -> List[Path]:
        """Declared packages plus an explicitly selected conventional root."""
        roots = self.pi_package_roots()
        if self._pi_package_forced and self.root_path not in roots:
            roots.append(self.root_path)
        return roots

    def pi_package_roots(self) -> List[Path]:
        """Cached, declaration-invariant Pi package claims from the shared scan."""
        from .discovery.pi import package_roots

        key = tuple(self.exclude_patterns)
        cached = getattr(self, "_pi_packages_cache", None)
        if cached is None or cached[0] != key:
            roots = package_roots(
                self.root_path,
                self._repository_scan().package_json_files,
                (p / "settings.json" for p in self.agent_tool_dirs(".pi")),
                self.is_path_excluded,
            )
            self._pi_packages_cache = (
                key,
                roots,
                {r for p in roots if (r := safe_resolve(p)) is not None},
            )
        return list(self._pi_packages_cache[1])

    def _pi_claim_set(self) -> Set[Path]:
        """Canonical identities for provenance; display roots keep their spelling."""
        self.pi_package_roots()
        assert self._pi_packages_cache is not None
        return self._pi_packages_cache[2]

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

    def _refresh_tool_types(self) -> None:
        """Fold committed tool configuration into the detected types.

        Runs at the end of ``__init__`` — tool evidence includes AGENTS.md
        and friends, which are not discovered when the packaging types are
        worked out — and again whenever a caller mutates
        ``exclude_patterns``, so an exclude added after construction takes
        that tool's rules with it.

        An explicit ``--type`` is the operator's answer to how the content is
        *packaged*, and it stays authoritative for that: every forced type
        survives, including a tool type the checkout has no marker for, so
        ``--type muse`` runs the Muse rules on a repository that has yet to
        commit ``.muse/hooks.json``. It is not an answer to which tools the
        checkout configures, so the detected tool types are unioned in rather
        than replaced — otherwise ``--type marketplace`` would quietly switch
        off every tool-gated rule and leave rules that read
        ``RepositoryType.X in context.repo_types`` reading a stale set.
        """
        detected = {RepositoryType(value) for value in self._detect_tool_type_values()}
        if self._overridden_types is not None:
            self.repo_types = set(self._overridden_types) | detected
        else:
            self.repo_types = (self.repo_types - TOOL_REPO_TYPES) | detected
            if self.pi_package_roots():
                self.repo_types.add(RepositoryType.PI_PACKAGE)
            else:
                self.repo_types.discard(RepositoryType.PI_PACKAGE)
        if len(self.repo_types) > 1:
            self.repo_types.discard(RepositoryType.UNKNOWN)
        elif not self.repo_types:
            self.repo_types.add(RepositoryType.UNKNOWN)

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
        from .formats.codex_manifest import portable_manifest

        recursive_agent_plugins = [
            plugin
            for plugin in self.agent_plugin_roots()
            if (provenance := self.provenance(plugin)).claude
            or (provenance.codex and portable_manifest(plugin, resolve=self.resolve_path) is None)
        ]
        skills = claude_discovery.discover_skills(
            self.root_path,
            agentskills=RepositoryType.AGENTSKILLS in self.repo_types,
            # A plugins/* layout can cause legacy Claude discovery to list an
            # Agent-only sibling. Only an actual Claude declaration permits
            # recursive Claude skill discovery for a portable package.
            plugins=[
                plugin
                for plugin in self.plugins
                if self.provenance(plugin).claude
                or not (self.provenance(plugin).agent_plugin or self.provenance(plugin).openclaw)
            ],
            codex_plugins=[
                p
                for p in self.codex_plugins
                if portable_manifest(p, resolve=self.resolve_path) is None
            ],
            # Config and catalog declarations retain custom skill paths
            # under unrelated --type overrides, just like their tree nodes.
            grok_plugins=self.grok_plugin_roots(),
            openclaw_plugins=[
                p for p in self.openclaw_plugin_roots() if not self.is_path_excluded(p / MANIFEST)
            ],
            openclaw_exclusive_plugins=[
                p
                for p in self.openclaw_plugin_roots()
                if self.provenance(p).ecosystems == frozenset({"openclaw"})
                and not self.is_path_excluded(p / MANIFEST)
            ],
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

        return self._filter_pi_skills(self._filter_cursor_skills(skills))

    def _filter_pi_skills(self, skills: List[Path]) -> List[Path]:
        """Assign native roles while retaining portable candidates for exclusions."""
        # Pi owns selection inside its packages and .pi/skills. A dual package
        # retains other consumers' discovery as well as Pi's own resources.
        pi_roots = [
            p for p in self.pi_discovery_roots() if not (self.provenance(p).ecosystems - {"pi"})
        ]
        from .discovery.pi import package_resources, project_resources

        native_skills = set()
        for directory in self.agent_tool_dirs(".pi"):
            native_skills.update(
                project_resources(
                    directory,
                    "skills",
                    self.root_path,
                    self.is_path_excluded,
                )
            )

        # Only selected resources adopt the native dialect; unselected portable
        # skills remain visible to their other consumers.
        for directory in self.pi_discovery_roots():
            manifest = directory / "package.json"
            data, _ = (
                read_json(manifest)
                if contained_resolve(manifest, self.root_path) is not None
                and not self.is_path_excluded(manifest)
                else (None, None)
            )
            if isinstance(data, dict) and "pi" in data and not isinstance(data["pi"], dict):
                # Invalid declarations receive config diagnostics, but cannot
                # take an existing portable skill out of its validation scope.
                continue
            native_skills.update(
                package_resources(
                    directory,
                    "skills",
                    self.root_path,
                    self.is_path_excluded,
                )
            )

        def owned_by_pi(path: Path) -> bool:
            declared = path / "SKILL.md" in native_skills
            if not declared:
                return False
            # A Pi package does not own another tool's customization root or
            # an independently declared nested package. Keep those consumers.
            for ancestor in (path, *path.parents):
                if ancestor.name.startswith(".") and ancestor.name != ".pi":
                    return False
                if self.provenance(ancestor).ecosystems - {"pi"}:
                    return False
                if ancestor in pi_roots:
                    return True
                if ancestor == self.root_path:
                    break
            return declared

        self._pi_portable_skills = [p for p in skills if owned_by_pi(p)]
        native = set(self._pi_portable_skills)
        return [p for p in skills if p not in native]
