"""Stateful plugin provenance and package-containment orchestration.

Discovery modules gather filesystem evidence without state.  This mixin is
the stateful seam used by :class:`skillsaw.context.RepositoryContext` to cache
that evidence and render one ownership verdict for every consumer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, List, Optional, Set, Tuple

from .formats.codex import codex_manifest_is_contained, codex_marker_escapes
from .paths import safe_exists, safe_resolve

if TYPE_CHECKING:
    from .lint_target import LintTarget


@dataclass(frozen=True)
class PluginProvenance:
    """Who claims a plugin directory, decided once and read everywhere.

    The single source of truth for every ecosystem-provenance question:
    which ecosystems declared the directory (``claude``, ``codex``, or
    ``agent-plugin``), and whether it is vendor-installed content. Rules and
    the lint tree consult this record so two call sites cannot disagree about
    ownership and a directory cannot fall between per-ecosystem attach paths.

    Evidence is filesystem-first (markers, contained manifests, catalog
    listings) and independent of ``--type`` overrides: an override changes
    what discovery walks, not what the author declared.
    """

    ecosystems: FrozenSet[str]
    installed: bool = False

    @property
    def codex_only(self) -> bool:
        """Codex claims the directory and Claude does not.

        Deliberately ``codex and not claude`` rather than "Codex is the sole
        ecosystem": the predicate asks whether Claude's looser reading of
        hooks and MCP still governs the directory, and only a Claude
        declaration answers yes. A dual ``codex`` + ``agent-plugin``
        directory is therefore codex_only — a portable Agent Plugins
        declaration is a second *contained* format, not a Claude one, so it
        must not restore Claude's leniency. A dual ``claude`` + ``codex``
        directory is not codex_only, which is what keeps
        ``TestDualManifestBackwardCompat``'s established Claude results
        intact.

        Load-bearing: this drives ``is_codex_only_plugin``,
        ``in_codex_only_plugin``, ``_is_containment_plugin``, and the
        conditional-strictness gates in the hooks and MCP rules.
        ``TestPluginProvenanceCodexOnlyTruthTable`` pins every combination.
        """
        return self.codex and not self.claude

    @property
    def claude(self) -> bool:
        return "claude" in self.ecosystems

    @property
    def codex(self) -> bool:
        return "codex" in self.ecosystems

    @property
    def agent_plugin(self) -> bool:
        return "agent-plugin" in self.ecosystems


class RepositoryProvenanceMixin:
    """Cached provenance and containment behavior for RepositoryContext.

    The host context supplies discovery results, claim-set builders, and
    exclusion policy. Keeping these stateful views together preserves one
    provenance source without making the state-free discovery layer depend on
    ``RepositoryContext``.

    **Host contract.** This mixin is not standalone: every member declared in
    the ``TYPE_CHECKING`` block below must be supplied by the class it is
    mixed into (today, :class:`skillsaw.context.RepositoryContext`). The
    declarations exist so the coupling is readable here instead of being
    reconstructed from attribute reads; they are annotations and stub bodies
    only, so nothing is defined at runtime and the host's real
    implementations are what execute.
    """

    if TYPE_CHECKING:
        # Required host state.
        root_path: Path
        _provenance_cache: Dict[Path, PluginProvenance]
        _format_scope_cache: Dict[Tuple[Path, str], bool]
        _contained_plugin_roots: Optional[Set[Path]]
        # Populated late in ``RepositoryContext.__init__`` — read through
        # ``getattr`` in :meth:`provenance`, see the note there.
        marketplace_entries: Dict[Path, Dict[str, Any]]

        # Required host behavior.
        def _codex_claim_set(self) -> Set[Path]: ...

        def _codex_claims_possible(self) -> bool: ...

        def _agent_plugin_claim_set(self) -> Set[Path]: ...

        def _agent_plugin_root_set(self) -> Set[Path]: ...

        def codex_plugin_roots(self) -> List[Path]: ...

        def is_codex_installed_plugin(self, plugin_dir: Path) -> bool: ...

    def provenance(self, plugin_dir: Path) -> PluginProvenance:
        """The :class:`PluginProvenance` for *plugin_dir*, cached per path.

        Cached under the path as given *and* under its resolved form, so a
        repeat consult for a path already seen costs a dict lookup and no
        syscall: every format-scoped rule re-asks this question for every
        node it iterates, and a ``realpath`` on each of those was the whole
        cost of the scope filter.

        The one place ecosystem-ownership evidence is gathered; every
        predicate below is a view over this record. Evidence, in declaration
        strength order:

        * ``claude`` — a ``.claude-plugin`` marker, or a listing in the Claude
          marketplace (``marketplace_entries``).
        * ``codex`` — a contained ``.codex-plugin/plugin.json``, or a local
          source listing in any Codex catalog.
        * ``agent-plugin`` — a contained package carrying an Agent Plugins
          schema identifier in root ``plugin.json``.

        Filesystem-first and independent of ``--type``: an override changes
        what discovery walks, not what the author declared.
        """
        cached = self._provenance_cache.get(plugin_dir)
        if cached is not None:
            return cached
        resolved = safe_resolve(plugin_dir)
        key = resolved if resolved is not None else plugin_dir
        cached = self._provenance_cache.get(key)
        if cached is not None:
            self._provenance_cache[plugin_dir] = cached
            return cached

        ecosystems = set()
        # ``getattr`` rather than a plain attribute read: this is genuinely
        # reachable, not defensiveness. ``RepositoryContext.__init__`` runs
        # type detection — which consults provenance — before it assigns
        # ``marketplace_entries``, so the early consults land here with the
        # attribute absent and must fall back to "no marketplace listing".
        # Those early records are discarded by the unconditional cache clear
        # at the end of ``apply_excludes``; see the ordering comment there.
        if safe_exists(plugin_dir / ".claude-plugin") or (
            resolved is not None and resolved in getattr(self, "marketplace_entries", {})
        ):
            ecosystems.add("claude")
        elif resolved is not None and resolved == safe_resolve(self.root_path / ".claude"):
            # The .claude/ directory is Claude by definition — a Codex
            # catalog listing "./.claude" as a local source must not turn
            # the repository's own command and agent content Codex-only
            # and switch its Claude-format checks off.
            ecosystems.add("claude")
        if codex_manifest_is_contained(plugin_dir) or (
            resolved is not None
            and resolved in self._codex_claim_set()
            # A catalog claim is a declaration about a directory, never a
            # licence to read through it: the marker gets the same
            # containment check discovery applies, so a claimed directory
            # whose ``.codex-plugin`` symlinks out of the tree is not Codex
            # and no Codex node is built over it. A directory with no marker
            # at all still passes — codex-plugin-json-valid reports the
            # missing manifest.
            and not codex_marker_escapes(plugin_dir)
        ):
            ecosystems.add("codex")
        if resolved is not None and resolved in self._agent_plugin_claim_set():
            ecosystems.add("agent-plugin")
        record = PluginProvenance(
            ecosystems=frozenset(ecosystems),
            installed=self.is_codex_installed_plugin(plugin_dir),
        )
        self._provenance_cache[key] = record
        self._provenance_cache[plugin_dir] = record
        return record

    def is_codex_only_plugin(self, plugin_dir: Path) -> bool:
        """Codex-claimed with no ``.claude-plugin`` marker.

        The provenance line the Claude-format rules gate on: a Codex-only
        directory is exempt from Claude manifest, frontmatter, and naming
        requirements, while ecosystem-neutral content and security rules
        still read its prose either way.
        """
        return self.provenance(plugin_dir).codex_only

    def in_format_scope(self, node: "LintTarget", ecosystem: str) -> bool:
        """Whether *ecosystem*'s format conventions govern *node*.

        The one gate behind ``Rule.provenance_scope``, read through
        ``Rule.scoped_find``: a node whose ``provenance_dir()`` is claimed
        exclusively by other ecosystems is out of scope. Unclaimed content
        stays in every scope, and a dual-manifest directory stays in scope
        for each of its ecosystems. Ownership comes from :meth:`provenance`;
        no fresh filesystem probes happen here.
        """
        owner_dir = node.provenance_dir()
        if owner_dir is None:
            return True
        key = (owner_dir, ecosystem)
        cached = self._format_scope_cache.get(key)
        if cached is None:
            ecosystems = self.provenance(owner_dir).ecosystems
            cached = not ecosystems or ecosystem in ecosystems
            self._format_scope_cache[key] = cached
        return cached

    def in_codex_only_plugin(self, path: Path) -> bool:
        """Whether *path* sits inside a Codex-only plugin, nearest owner first."""
        owner = self.codex_plugin_owning(path)
        return owner is not None and self.provenance(owner).codex_only

    def codex_plugin_owning(self, path: Path) -> Optional[Path]:
        """The Codex plugin *path* sits in, nearest first, or ``None``.

        Nearest rather than first: a repository root that is itself a plugin
        contains nested ones, so an outer match would let content escape the
        plugin that actually ships it.
        """
        roots = set(self.codex_plugin_roots())
        if not roots:
            return None
        resolved = safe_resolve(path)
        if resolved is None:
            return None
        for candidate in (resolved, *resolved.parents):
            if candidate in roots:
                return candidate
        return None

    def contained_plugin_owning(self, path: Path) -> Optional[Path]:
        """Nearest plugin root whose package files have containment semantics.

        Codex and Agent Plugins both require supplied files to resolve inside
        the package. Claude's legacy format has no equivalent package-wide
        contract, so it deliberately remains outside this helper.
        """
        if self._contained_plugin_roots is None:
            self._contained_plugin_roots = set(self.codex_plugin_roots()) | set(
                self._agent_plugin_root_set()
            )
        roots = self._contained_plugin_roots
        if not roots:
            return None
        resolved = safe_resolve(path)
        if resolved is None:
            return None
        for candidate in (resolved, *resolved.parents):
            if candidate in roots:
                return candidate
        return None

    def _contained_plugin_claim_boundary(self, parent: Path) -> Optional[Path]:
        """Resolved containment-governed package owning *parent*, if any.

        A lexical ancestor walk, nearest first — not resolution-based like
        :meth:`contained_plugin_owning`, because resolving first would follow
        the very symlinks the boundary exists to reject. Ownership comes from
        :meth:`provenance`.
        """
        if not self._contained_plugin_claims_possible():
            return None
        agent_roots = self._agent_plugin_root_set()
        for candidate in (parent, *parent.parents):
            resolved = safe_resolve(candidate)
            if resolved is not None and (
                resolved in agent_roots or self.provenance(candidate).codex_only
            ):
                return resolved
            if candidate == self.root_path or candidate.parent == candidate:
                break
        return None

    def _contained_plugin_claims_possible(self) -> bool:
        """Whether a skill walk can encounter a package containment boundary."""
        return self._codex_claims_possible() or bool(self._agent_plugin_root_set())

    def _is_containment_plugin(self, path: Path) -> bool:
        """Whether *path* itself begins a package containment boundary."""
        resolved = safe_resolve(path)
        return resolved is not None and (
            resolved in self._agent_plugin_root_set() or self.provenance(path).codex_only
        )
