"""Validate Cursor marketplace metadata and local source references."""

from skillsaw.blocks.cursor import CursorMarketplaceBlock
from skillsaw.formats import cursor
from skillsaw.formats.cursor_schema import validator
from skillsaw.paths import safe_is_dir
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Rule, Severity
from skillsaw.diagnostics import safe_display

_SHOWN = 5


class CursorMarketplaceValidRule(Rule):
    since = "0.21.0"
    repo_types = frozenset({RepositoryType.CURSOR_MARKETPLACE})

    @property
    def rule_id(self):
        return "cursor-marketplace-json-valid"

    @property
    def description(self):
        return "Cursor marketplaces must contain valid entries with unique names and resolvable local sources"

    def default_severity(self):
        return Severity.ERROR

    def check(self, context):
        violations = []
        for block in context.lint_tree.find(CursorMarketplaceBlock):
            try:
                oversized = block.path.stat().st_size > 10 * 1024 * 1024
            except OSError:
                oversized = False  # The parser reports unreadable files.
            if oversized:
                violations.append(
                    self.violation("Marketplace exceeds Cursor's 10 MB limit", file_path=block.path)
                )
            if block.parse_error or block.raw_data is None:
                violations.append(
                    self.violation(
                        f"Invalid Cursor marketplace: {block.parse_error or 'expected a JSON object'}",
                        file_path=block.path,
                    )
                )
                continue
            data = block.raw_data
            for error in validator("marketplace").iter_errors(data):
                location = ".".join(str(p) for p in error.absolute_path) or "marketplace"
                violations.append(
                    self.violation(
                        f"{safe_display(location)}: {safe_display(error.message)}",
                        file_path=block.path,
                    )
                )
            entries = data.get("plugins")
            if not isinstance(entries, list):
                continue
            names = set()
            missing = []
            metadata = data.get("metadata")
            prefix = metadata.get("pluginRoot", "") if isinstance(metadata, dict) else ""
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                if isinstance(name, str):
                    if name in names:
                        violations.append(
                            self.violation(
                                f"Duplicate plugin name {safe_display(repr(name))}; give each entry a unique name",
                                file_path=block.path,
                            )
                        )
                    names.add(name)
                source = cursor.local_source(entry.get("source"))
                if source is None or not isinstance(prefix, str):
                    continue
                path = cursor.source_path(block.path.parent.parent, prefix, source)
                if path is None:
                    violations.append(
                        self.violation(
                            f"Plugin {safe_display(repr(name))}: source must be a relative path that stays inside this marketplace",
                            file_path=block.path,
                        )
                    )
                elif not safe_is_dir(path):
                    missing.append(safe_display(repr(name)))
            if missing:
                # One finding per catalog: a copied or stale marketplace
                # otherwise reports every entry separately.
                shown = ", ".join(missing[:_SHOWN])
                if len(missing) > _SHOWN:
                    shown += f", and {len(missing) - _SHOWN} more"
                noun = "entry has" if len(missing) == 1 else "entries have"
                violations.append(
                    self.violation(
                        f"{len(missing)} plugin {noun} no local plugin directory: {shown}; "
                        "point each source at an existing directory inside this marketplace",
                        file_path=block.path,
                    )
                )
        return violations
