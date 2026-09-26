"""Cached Cursor declaration views for RepositoryContext."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from skillsaw.discovery import cursor as discovery
from skillsaw.formats import cursor
from skillsaw.repository_types import RepositoryType


class RepositoryCursorMixin:
    def _init_cursor(self, repo_types: Iterable[RepositoryType] | None) -> None:
        self._cursor_cache = None
        self._cursor_forced = set(repo_types or ())
        self._cursor_enabled = repo_types is None or bool(
            self._cursor_forced & {RepositoryType.CURSOR_PLUGIN, RepositoryType.CURSOR_MARKETPLACE}
        )

    def _cursor_evidence(self):
        if self._cursor_cache is None:
            markers = self.agent_tool_dirs(cursor.MARKER)
            catalogs = discovery.catalogs(self.root_path, markers, self.is_path_excluded)
            entries = discovery.entries(catalogs)
            roots = discovery.plugins(self.root_path, markers, entries, self.is_path_excluded)
            # A forced discovery root is not a filesystem ownership declaration.
            claims = set(roots)
            if RepositoryType.CURSOR_PLUGIN in self._cursor_forced and not roots:
                roots = discovery.plugins(
                    self.root_path, (), [self.root_path], self.is_path_excluded
                )
            self._cursor_cache = (catalogs, entries, roots, claims)
        return self._cursor_cache

    def cursor_plugin_roots(self) -> list[Path]:
        return self._cursor_evidence()[2]

    def cursor_marketplace_paths(self) -> list[Path]:
        if not self._cursor_enabled:
            return []
        paths = self._cursor_evidence()[0]
        if not paths and RepositoryType.CURSOR_MARKETPLACE in self._cursor_forced:
            return [self.root_path / cursor.MARKER / "marketplace.json"]
        return paths

    def cursor_views(self, root: Path) -> list[tuple[Path, dict[str, Any]]]:
        """Effective manifests, one per catalog entry or standalone plugin."""
        manifest = root / cursor.MARKER / "plugin.json"
        data, error = cursor.read_manifest(manifest)
        native = data if isinstance(data, dict) and not error else {}
        entries = self._cursor_evidence()[1].get(root, [])
        views = []
        seen = set()
        fields = (*cursor.COMPONENT_EXTENSIONS, "hooks", "mcpServers")
        for origin, entry in entries:
            effective = {**entry, **native}
            # Catalog metadata is checked on the catalog. Identical component
            # declarations must not multiply directory walks or inline findings.
            components = {key: effective[key] for key in fields if key in effective}
            key = (origin, json.dumps(components, sort_keys=True))
            if key not in seen:
                seen.add(key)
                views.append((origin, effective))
        return views or [(manifest, native)]

    def cursor_skills(self) -> set[Path]:
        roots = set(self.distinct_plugin_dirs())
        return {
            p
            for root in self.cursor_plugin_roots()
            for _, data in self.cursor_views(root)
            for p in cursor.skill_dirs(root, data, self.is_path_excluded, resolve=self.resolve_path)
            if not self.is_path_excluded(p)
            and not self.is_path_excluded(p / "SKILL.md")
            and next((parent for parent in (p, *p.parents) if parent in roots), None) == root
        }

    def _reset_cursor(self) -> None:
        before = set(self.cursor_plugin_roots())
        self._cursor_cache = None
        after = set(self.cursor_plugin_roots())
        dropped = before - after
        if dropped:
            active = (
                set(self.plugins)
                | set(self.codex_plugin_roots())
                | set(self.grok_plugin_roots())
                | set(self.agent_plugin_roots())
                | set(self.antigravity_plugin_roots())
                | set(self.openclaw_plugin_roots())
                | set(self.pi_discovery_roots())
                | after
            )
            self.skills = [
                p
                for p in self.skills
                if not any(p.is_relative_to(r) for r in dropped)
                or any(p.is_relative_to(r) for r in active)
            ]
        if self._overridden_types is None:
            for kind, present in (
                (RepositoryType.CURSOR_PLUGIN, bool(after)),
                (RepositoryType.CURSOR_MARKETPLACE, bool(self.cursor_marketplace_paths())),
            ):
                if present:
                    self.repo_types.add(kind)
                else:
                    self.repo_types.discard(kind)

    def _cursor_claim_set(self) -> set[Path]:
        return self._cursor_evidence()[3]

    def _filter_cursor_skills(self, discovered: Iterable[Path]) -> list[Path]:
        """Replace generic skill discovery only under Cursor's own skill roots.

        Inside an exclusively Cursor package, Cursor's resolution decides
        which skills sit under its declared (or default) ``skills`` path.
        A SKILL.md elsewhere in the package never loads in Cursor, but it
        is still the portable Agent Skills layout and stays linted.
        """
        if not self.cursor_plugin_roots():
            return list(discovered)
        skill_roots = {
            p: [
                component
                for _, data in self.cursor_views(p)
                for component in cursor.component_paths(p, data, "skills")
            ]
            for p in self.cursor_plugin_roots()
            if self.provenance(p).ecosystems == frozenset({"cursor"})
        }
        candidates = list(discovered)
        if skill_roots:
            roots = set(self.distinct_plugin_dirs())

            def resolved_by_cursor(path: Path) -> bool:
                owner = next((p for p in (path, *path.parents) if p in roots), None)
                return any(path.is_relative_to(c) for c in skill_roots.get(owner, ()))

            candidates = [p for p in candidates if not resolved_by_cursor(p)]
        candidates.extend(sorted(self.cursor_skills()))
        # Different hosts can select an alias and its canonical directory.
        # Deduplicate containers as well as their physical SKILL.md children,
        # or the tree gains an empty SkillNode reporting a missing entrypoint.
        by_resolved: dict[Path, Path] = {}
        for path in candidates:
            resolved = self.resolve_path(path)
            if resolved is not None:
                by_resolved.setdefault(resolved, path)
        return sorted(by_resolved.values())
