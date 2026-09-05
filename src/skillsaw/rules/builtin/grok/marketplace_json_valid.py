"""
Rule: grok-marketplace-json-valid

Validates `.grok-plugin/marketplace.json` catalogs for Grok Build.
Ensures catalogs have valid JSON syntax, proper plugin array structures,
resolvable local paths, and pinned Git repositories.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import grok
from skillsaw.formats.grok_catalog import catalog_type_errors, read_catalog_json
from skillsaw.formats.grok_install import effective_install_pin
from skillsaw.lint_target import GrokMarketplaceConfigNode
from skillsaw.paths import (
    contained_resolve,
    safe_exists,
    safe_is_dir,
    safe_resolve,
)
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import GROK_MARKETPLACE_REPO_TYPES, escape_reason


class GrokMarketplaceJsonValidRule(Rule):
    """Validate a Grok Build marketplace catalog"""

    since = "0.20.0"

    repo_types = GROK_MARKETPLACE_REPO_TYPES

    config_schema = {
        "require-sha": {
            "type": "bool",
            "default": True,
            "description": (
                "Report a url source with no full commit pin in 'sha' or 'ref', "
                "which Grok installs with an unpinned git clone"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "grok-marketplace-json-valid"

    @property
    def description(self) -> str:
        return ".grok-plugin/marketplace.json must be valid JSON with installable entries"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for node in context.lint_tree.find(GrokMarketplaceConfigNode):
            catalog = node.path
            data, error = read_catalog_json(catalog)
            if error:
                # An absent file is a ``--type``-seeded node, not a syntax
                # error: "Invalid JSON: Failed to read" would name the wrong
                # defect.
                message = (
                    f"Invalid JSON: {error}"
                    if safe_exists(catalog)
                    else "Marketplace file not found"
                )
                violations.append(self.violation(message, file_path=catalog))
                continue
            if not isinstance(data, dict):
                violations.append(
                    self.violation("Marketplace catalog must be a JSON object", file_path=catalog)
                )
                continue
            errors = catalog_type_errors(data)
            if errors:
                violations.extend(self.violation(message, file_path=catalog) for message in errors)
                # A bad typed member rejects the catalog as a whole, so
                # installation advice about its other entries is misleading.
                continue
            violations.extend(self._check_entries(data.get("plugins", []), catalog))

        return violations

    def _check_entries(self, entries: List[Any], catalog: Path) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        # Grok resolves a local source against the marketplace root — the
        # directory holding ``.grok-plugin/`` — so a package that is a
        # marketplace of its own resolves against the package.
        marketplace_root = catalog.parent.parent
        resolved_root = safe_resolve(marketplace_root)
        # Duplicates are counted per catalog. Two independent marketplaces
        # in one monorepo shipping the same plugin name is a packaging
        # choice; two entries in one catalog is the measured install
        # failure.
        by_name: Dict[str, List[int]] = {}

        for index, entry in enumerate(entries):
            source_violations, target, installs = self._check_source(
                entry, index, catalog, marketplace_root, resolved_root
            )
            violations.extend(source_violations)
            if not installs:
                # An entry Grok drops installs nothing, so it can collide
                # with nothing. Counting it would report a duplicate name
                # beside the defect that is already the whole reason the
                # entry is gone.
                continue
            resolved = self._resolved_name(entry, target)
            if resolved is not None:
                by_name.setdefault(resolved, []).append(index)

        for name, indices in by_name.items():
            if len(indices) < 2:
                continue
            where = ", ".join(f"plugins[{index}]" for index in indices)
            violations.append(
                self.violation(
                    f"Duplicate plugin name '{safe_display(name)}' at {where}",
                    file_path=catalog,
                )
            )

        return violations

    def _check_source(
        self,
        entry: Dict[str, Any],
        index: int,
        catalog: Path,
        marketplace_root: Path,
        resolved_root: Optional[Path],
    ) -> Tuple[List[RuleViolation], Optional[Path], bool]:
        """Validate an entry's source.

        Returns the findings, the local directory the source names, and
        whether Grok installs anything from the entry at all — a dropped
        entry creates no installation ambiguity, so it takes no part in the
        duplicate-name accounting above.
        """
        source = entry.get("source")
        if source is None:
            return (
                [self.violation(f"plugins[{index}] missing required 'source'", file_path=catalog)],
                None,
                False,
            )
        if isinstance(source, str) and not source:
            return (
                [self.violation(f"plugins[{index}].source is an empty path", file_path=catalog)],
                None,
                False,
            )

        if grok.is_url_source(source):
            # An unpinned or oddly-cased sha still clones; an invalid path
            # prevents installation and cannot create an installed-name
            # collision. Pin policy is checked separately below.
            path = source.get("path")
            installs = bool(source["url"]) and (
                path is None or grok.grok_marketplace_relative_path(path) is not None
            )
            return self._check_url(source, index, catalog), None, installs
        # Keep the original spelling for diagnostics. Discovery and parity
        # use grok_local_source_path's normalized, valid-only result.
        local = source if isinstance(source, str) else source.get("path")
        if local is not None:
            violations, target = self._check_local(
                local, index, catalog, marketplace_root, resolved_root
            )
            return violations, target, target is not None
        # An object naming neither a directory here nor a repository to
        # clone. A warning rather than an error: the loader keys on the
        # fields rather than on a type, so a source shape added upstream
        # must not break a catalog that works.
        return (
            [
                self.violation(
                    f"plugins[{index}].source names neither a local 'path' nor a 'url'",
                    file_path=catalog,
                    severity=Severity.WARNING,
                )
            ],
            None,
            False,
        )

    def _check_local(
        self,
        value: str,
        index: int,
        catalog: Path,
        marketplace_root: Path,
        resolved_root: Optional[Path],
    ) -> Tuple[List[RuleViolation], Optional[Path]]:
        if resolved_root is None:
            return [], None
        normalized = grok.grok_marketplace_relative_path(value)
        reason = escape_reason(
            normalized if normalized is not None else value, resolved_root, "marketplace root"
        )
        if normalized is None or reason:
            reason = reason or (
                "must name a relative subdirectory without empty, '.', '..' or ':' path "
                "components; only one leading './' is allowed"
            )
            return (
                [
                    self.violation(
                        f"plugins[{index}].source: '{safe_display(value)}' {reason}",
                        file_path=catalog,
                    )
                ],
                None,
            )
        target = contained_resolve(marketplace_root / normalized, resolved_root)
        if target is None or not safe_is_dir(target):
            return (
                [
                    self.violation(
                        f"plugins[{index}].source: '{safe_display(value)}' is not a "
                        "directory under the marketplace root",
                        file_path=catalog,
                    )
                ],
                None,
            )
        if grok.grok_marker_escapes(target):
            # Discovery drops a directory whose ``.grok-plugin`` marker or
            # manifest resolves outside it, so no plugin node is built and
            # none of the plugin checks run — the entry installs another
            # plugin's manifest and nothing here would otherwise say so.
            return (
                [
                    self.violation(
                        f"plugins[{index}].source: '{safe_display(value)}' has a "
                        f"'{grok.PLUGIN_DIR_NAME}' that resolves outside it",
                        file_path=catalog,
                    )
                ],
                None,
            )
        return [], target

    def _check_url(self, source: Dict[str, Any], index: int, catalog: Path) -> List[RuleViolation]:
        """Check the effective install pin without changing display-index SHA semantics."""
        violations: List[RuleViolation] = []
        url = source.get("url")
        if not isinstance(url, str) or not url:
            # A non-null empty URL selects remote handling but names no
            # repository to clone; it must not fall back to a local path.
            return [
                self.violation(
                    f"plugins[{index}].source is a url source with no 'url' to clone",
                    file_path=catalog,
                )
            ]
        pin_field, sha = effective_install_pin(source.get("ref"), source.get("sha"))
        if sha is None:
            if self.setting("require-sha"):
                violations.append(
                    self.violation(
                        f"plugins[{index}].source has no 'sha' or full-commit 'ref' pin",
                        file_path=catalog,
                    )
                )
        elif not grok.SHA_RE.fullmatch(sha):
            lengths = " or ".join(str(length) for length in sorted(grok.SHA_LENGTHS))
            violations.append(
                self.violation(
                    f"plugins[{index}].source.{pin_field} '{safe_display(sha)}' is not a "
                    f"{lengths} character hex commit id",
                    file_path=catalog,
                )
            )
        elif len(sha) != grok.UPSTREAM_SHA_LENGTH or sha != sha.lower():
            # One advisory for both halves of the same gap: Grok installs a
            # 64-hex or uppercase value, and ``validate-catalog.py`` in
            # xai-org/plugin-marketplace refuses it.
            violations.append(
                self.violation(
                    f"plugins[{index}].source.{pin_field} '{safe_display(sha)}' is not "
                    f"{grok.UPSTREAM_SHA_LENGTH} lowercase hex characters, which the "
                    "upstream marketplace validator requires",
                    file_path=catalog,
                    severity=Severity.INFO,
                )
            )

        path = source.get("path")
        if path is not None and grok.grok_marketplace_relative_path(path) is None:
            violations.append(
                self.violation(
                    f"plugins[{index}].source.path '{safe_display(path)}' must be a "
                    "relative subdirectory of the cloned repository without empty, '.', '..' "
                    "or ':' path components; only one leading './' is allowed",
                    file_path=catalog,
                    severity=self.scope_severity(Severity.WARNING),
                )
            )
        return violations

    def _resolved_name(self, entry: Dict[str, Any], target: Optional[Path]) -> Optional[str]:
        """The name Grok surfaces the entry under.

        For a local source that is the plugin's own manifest name, not the
        catalog's: an entry named ``Bad Name!`` pointing at ``plugins/canary``
        surfaces as ``canary`` and collides with an entry named ``canary``.
        A url source has no manifest to read here, so the catalog name is
        the best available.
        """
        if target is not None:
            return grok.grok_plugin_name(target)
        name = entry.get("name")
        return name if isinstance(name, str) and name else None
