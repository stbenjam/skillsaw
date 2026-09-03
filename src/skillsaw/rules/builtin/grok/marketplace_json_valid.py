"""
Rule: grok-marketplace-json-valid

The shape of a Grok Build catalog, and severity that carries what each
defect costs. A catalog Grok cannot read is discarded whole and discovery
falls back to scanning ``plugins/`` — so a repository keeping third-party
plugins anywhere else loses exactly those, and the browser still looks
right. An entry defect is quieter still: the entry is dropped with no
diagnostic at add or list time.

The loader keys a local source on ``path`` alone. ``{"type": "local"}``,
``{"source": "local"}``, a bare string, an object with no discriminator and
one with a bogus ``type`` all install identically, so requiring a
discriminator would be a false positive on catalogs that work.

Only :class:`GrokMarketplaceConfigNode` is iterated, a node type only Grok
populates, so the rule declares no ``provenance_scope``.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import grok
from skillsaw.lint_target import GrokMarketplaceConfigNode
from skillsaw.paths import (
    contained_resolve,
    has_parent_traversal,
    is_absolute_path,
    safe_exists,
    safe_is_dir,
    safe_resolve,
)
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import strict_json

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
                "Report a url source with no 'sha', which Grok installs with an "
                "unpinned git clone"
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
        # Every defect at this severity costs a plugin: the catalog is
        # discarded, the entry is dropped, the install is refused, or the
        # clone is unpinned. None of it is reported by Grok.
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for node in context.lint_tree.find(GrokMarketplaceConfigNode):
            catalog = node.path
            data, error = strict_json(catalog)
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
            if "plugins" not in data:
                violations.append(self.violation("Missing 'plugins' array", file_path=catalog))
                continue
            entries = data["plugins"]
            if not isinstance(entries, list):
                violations.append(self.violation("'plugins' must be an array", file_path=catalog))
                continue
            violations.extend(self._check_entries(entries, catalog))

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
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(f"plugins[{index}] must be an object", file_path=catalog)
                )
                continue
            violations.extend(self._check_name(entry, index, catalog))
            source_violations, target = self._check_source(
                entry, index, catalog, marketplace_root, resolved_root
            )
            violations.extend(source_violations)
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

    def _check_name(self, entry: Dict[str, Any], index: int, catalog: Path) -> List[RuleViolation]:
        """An entry with no usable ``name`` is dropped from the catalog.

        The *value* is not checked against Grok's plugin-name rule: a local
        entry named ``Bad Name!`` loads and surfaces under the name its
        manifest declares, so demanding the format here would report a
        catalog that works.
        """
        if "name" not in entry:
            return [self.violation(f"plugins[{index}] missing required 'name'", file_path=catalog)]
        name = entry["name"]
        if not isinstance(name, str):
            return [
                self.violation(
                    f"plugins[{index}] 'name' must be a string, got '{safe_display(name)}'",
                    file_path=catalog,
                )
            ]
        if not name:
            return [
                self.violation(
                    f"plugins[{index}] required field 'name' is an empty string",
                    file_path=catalog,
                )
            ]
        return []

    def _check_source(
        self,
        entry: Dict[str, Any],
        index: int,
        catalog: Path,
        marketplace_root: Path,
        resolved_root: Optional[Path],
    ) -> Tuple[List[RuleViolation], Optional[Path]]:
        """Validate an entry's source; return it and the local directory it names."""
        source = entry.get("source")
        if source is None:
            return (
                [self.violation(f"plugins[{index}] missing required 'source'", file_path=catalog)],
                None,
            )
        if not isinstance(source, (str, dict)):
            return (
                [
                    self.violation(
                        f"plugins[{index}].source must be a path string or an object",
                        file_path=catalog,
                    )
                ],
                None,
            )
        if isinstance(source, str) and not source:
            return (
                [self.violation(f"plugins[{index}].source is an empty path", file_path=catalog)],
                None,
            )

        local = grok.grok_local_source_path(source)
        if local is not None:
            return self._check_local(local, index, catalog, marketplace_root, resolved_root)
        if grok.is_url_source(source):
            return self._check_url(source, index, catalog), None
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
        reason = escape_reason(value, resolved_root, "marketplace root")
        if reason:
            return (
                [
                    self.violation(
                        f"plugins[{index}].source: '{safe_display(value)}' {reason}",
                        file_path=catalog,
                    )
                ],
                None,
            )
        target = contained_resolve(marketplace_root / value, resolved_root)
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
        return [], target

    def _check_url(self, source: Dict[str, Any], index: int, catalog: Path) -> List[RuleViolation]:
        """A url source is cloned at install; the ``sha`` is what pins it."""
        violations: List[RuleViolation] = []
        url = source.get("url")
        if not isinstance(url, str) or not url:
            # ``{"source": "url"}`` and ``{"url": null}`` both select this
            # branch and name no repository to clone.
            return [
                self.violation(
                    f"plugins[{index}].source is a url source with no 'url' to clone",
                    file_path=catalog,
                )
            ]
        sha = source.get("sha")
        if sha is None:
            if self.setting("require-sha"):
                violations.append(
                    self.violation(
                        f"plugins[{index}].source has no 'sha'",
                        file_path=catalog,
                    )
                )
        elif not isinstance(sha, str):
            violations.append(
                self.violation(
                    f"plugins[{index}].source.sha must be a string, got '{safe_display(sha)}'",
                    file_path=catalog,
                )
            )
        elif not grok.SHA_RE.fullmatch(sha):
            lengths = " or ".join(str(length) for length in sorted(grok.SHA_LENGTHS))
            violations.append(
                self.violation(
                    f"plugins[{index}].source.sha '{safe_display(sha)}' is not a "
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
                    f"plugins[{index}].source.sha '{safe_display(sha)}' is not "
                    f"{grok.UPSTREAM_SHA_LENGTH} lowercase hex characters, which the "
                    "upstream marketplace validator requires",
                    file_path=catalog,
                    severity=Severity.INFO,
                )
            )

        path = source.get("path")
        if isinstance(path, str) and path:
            if is_absolute_path(path) or has_parent_traversal(path) or "\\" in path:
                violations.append(
                    self.violation(
                        f"plugins[{index}].source.path '{safe_display(path)}' must be a "
                        "relative subdirectory of the cloned repository",
                        file_path=catalog,
                        severity=Severity.WARNING,
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
