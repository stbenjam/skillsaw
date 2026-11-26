"""
Rule: zcode-marketplace-json-valid

Checks a ZCode marketplace catalog — the repository-root ``marketplace.json``
of a repository that ships ZCode plugins — the way ``zcode plugins
marketplace add`` and ``zcode plugins install`` read it.
"""

from pathlib import Path
from typing import Any, Dict, List

from skillsaw.context import RepositoryContext
from skillsaw.formats import zcode
from skillsaw.lint_target import ZCodeMarketplaceConfigNode
from skillsaw.diagnostics import safe_display
from skillsaw.paths import (
    contained_resolve,
    is_absolute_path,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_resolve,
)
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.utils import read_json_strict

from ._helpers import ZCODE_MARKETPLACE_REPO_TYPES


class ZCodeMarketplaceJsonValidRule(Rule):
    """Check that a ZCode marketplace catalog lists plugins ZCode can install"""

    since = "0.23.0"

    repo_types = ZCODE_MARKETPLACE_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "zcode-marketplace-json-valid"

    @property
    def description(self) -> str:
        return "A ZCode marketplace.json must parse, be named, and list installable local plugins"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for node in context.lint_tree.find(ZCodeMarketplaceConfigNode):
            violations.extend(self._check_catalog(node.path))
        return violations

    def _check_catalog(self, path: Path) -> List[RuleViolation]:
        if not safe_exists(path):
            return [
                self.violation(
                    "No marketplace.json at the repository root; ZCode has no catalog to add",
                    path,
                )
            ]
        if not safe_is_file(path):
            # A directory, FIFO or device: reading it could hang the lint.
            return [self.violation("marketplace.json is not a regular file", path)]
        # ``JSON.parse``: non-finite tokens are syntax errors, repeated keys are not.
        data, error = read_json_strict(path, allow_duplicate_keys=True)
        if error:
            return [
                self.violation(f"Invalid JSON: {error}; ZCode cannot add this marketplace", path)
            ]
        if not isinstance(data, dict):
            return [self.violation("Catalog must be a JSON object", path)]
        violations: List[RuleViolation] = []
        name = data.get("name")
        if not (isinstance(name, str) and zcode.NAME_RE.match(name.strip())):
            # marketplace.ts:2181-2184: the catalog is rejected outright.
            violations.append(
                self.violation(
                    f"Marketplace name {safe_display(name)!r} is missing or invalid: ZCode requires 1-128 "
                    "characters of lowercase letters, digits, '.', '_' or '-'; ZCode cannot "
                    "add this marketplace",
                    path,
                )
            )
        if not isinstance(data.get("plugins"), (list, dict)):
            # ZCode still adds the marketplace, with no plugins in it.
            violations.append(
                self.violation(
                    "'plugins' must be an array of entries (or an object keyed by plugin name); "
                    "ZCode adds this marketplace with no plugins",
                    path,
                    severity=self.scope_severity(Severity.WARNING),
                )
            )
            return violations
        base = zcode.catalog_plugin_base(path.parent, data)
        root = safe_resolve(path.parent)
        if root is None:
            return violations
        for index, entry in enumerate(zcode.catalog_entries(data)):
            violations.extend(self._check_entry(path, root, base, index, entry))
        return violations

    def _check_entry(
        self, path: Path, root: Path, base: Path, index: int, entry: Any
    ) -> List[RuleViolation]:
        if not isinstance(entry, dict):
            return [self.violation(f"plugins[{index}] must be an object; ZCode drops it", path)]
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            return [self.violation(f"plugins[{index}] has no 'name'; ZCode drops it", path)]
        label = f"Plugin {safe_display(name)!r}"
        if not zcode.NAME_RE.match(name.strip()):
            # The installed manifest must carry this name, and a manifest
            # name has to match the pattern, so the entry can never install.
            return [
                self.violation(
                    f"{label}: name must be 1-128 characters of lowercase letters, digits, "
                    "'.', '_' or '-'; no ZCode plugin can match it, so it never installs",
                    path,
                )
            ]
        source = entry.get("source")
        if isinstance(source, dict):
            kind = source.get("source")
            if not isinstance(kind, str):
                kind = None  # a missing or non-string kind is unsupported, and unhashable
            if kind in zcode.UNSUPPORTED_SOURCE_KINDS:
                return [self.violation(f"{label}: ZCode does not install {kind} sources", path)]
            if kind not in zcode.REMOTE_SOURCE_KINDS and kind != "directory":
                return [
                    self.violation(
                        f"{label}: unsupported source kind {safe_display(kind)!r}; ZCode accepts github, "
                        "git, url, git-subdir or directory",
                        path,
                    )
                ]
            missing = [
                field
                for field in zcode.SOURCE_REQUIRED_FIELDS[kind]
                if not (isinstance(source.get(field), str) and source[field].strip())
            ]
            if missing:
                return [
                    self.violation(
                        f"{label}: a {kind} source needs a non-empty "
                        f"{' and '.join(repr(m) for m in missing)}; ZCode cannot install it",
                        path,
                    )
                ]
            if kind == "url":
                # A non-string ``type`` reads as empty, which is git
                # (``adapters/src/plugins/marketplace.ts:1468-1484``).
                url_type = source.get("type") if isinstance(source.get("type"), str) else ""
                if url_type == "zip" and not isinstance(source.get("sha256"), str):
                    return [
                        self.violation(
                            f"{label}: a zip url source needs a 'sha256'; ZCode cannot install it",
                            path,
                        )
                    ]
                if url_type not in ("", "git", "zip"):
                    return [
                        self.violation(
                            f"{label}: url source 'type' must be git or zip "
                            f"(got {safe_display(url_type)!r}); ZCode cannot install it",
                            path,
                        )
                    ]
            return []  # remote or absolute: nothing in this checkout to check
        if source is not None and not isinstance(source, str):
            return [self.violation(f"{label}: 'source' must be a string or an object", path)]
        plugin_dir = zcode.entry_local_source(entry, base)
        if plugin_dir is None:
            if isinstance(source, str) and source in ("filesystem", "sea"):
                return []
            if isinstance(source, str) and is_absolute_path(source):
                # ZCode falls back to the path as given, on the machine
                # installing it, so this checkout cannot judge it.
                return []
            return [
                self.violation(
                    f"{label}: source {safe_display(source)!r} leaves the marketplace directory; "
                    "ZCode cannot install it",
                    path,
                )
            ]
        if safe_is_dir(plugin_dir) and contained_resolve(plugin_dir, root) is None:
            # A symlink in the checkout whose target is outside it: never
            # read a manifest from there.
            return [
                self.violation(
                    f"{label}: source {safe_display(source)!r} resolves outside the "
                    "marketplace directory",
                    path,
                )
            ]
        if not safe_is_dir(plugin_dir):
            where = (
                repr(safe_display(source))
                if source is not None
                else f"'{safe_display(plugin_dir.name)}/' (from its name)"
            )
            return [
                self.violation(
                    f"{label}: source {where} is not a directory; ZCode cannot install it", path
                )
            ]
        return self._check_manifest(path, label, name.strip(), entry, plugin_dir)

    def _check_manifest(
        self, path: Path, label: str, name: str, entry: Dict[str, Any], plugin_dir: Path
    ) -> List[RuleViolation]:
        """The install-time checks ZCode runs on a listed local plugin.

        ``validatePluginRoot`` (``adapters/src/plugins/marketplace.ts:2429-2490``
        in ``zai-org/ZCode``): a manifest must exist unless the entry sets
        ``strict: false``, and its ``name`` must equal the entry's. Manifest
        parse errors belong to the plugin manifest rules.
        """
        manifest_path = zcode.zcode_manifest_path(plugin_dir)
        if manifest_path is None:
            if entry.get("strict") is False:
                return []
            return [
                self.violation(
                    f"{label}: '{safe_display(plugin_dir.name)}/' has no .zcode-plugin/plugin.json (or "
                    ".claude-plugin/ or .codex-plugin/ manifest); ZCode refuses to install it. "
                    'Add a manifest, or set "strict": false to install from the entry alone',
                    path,
                )
            ]
        data, error = read_json_strict(manifest_path, allow_duplicate_keys=True)
        if error or not isinstance(data, dict):
            return []
        manifest_name = data.get("name")
        if isinstance(manifest_name, str) and manifest_name.strip() != name:
            return [
                self.violation(
                    f"{label}: its manifest is named {safe_display(manifest_name.strip())!r}; ZCode refuses "
                    "to install a plugin whose manifest name differs from the catalog entry",
                    path,
                )
            ]
        return []
