"""
Rule: zcode-plugin-json-valid

Checks a ``.zcode-plugin/plugin.json`` the way ZCode's plugin loader reads
it: a JSON object with a valid ``name``, component paths that stay inside
the plugin, manifest-declared commands ZCode can materialize, and no
components ZCode ignores.
"""

from typing import Any, Dict, List

from skillsaw.context import RepositoryContext
from skillsaw.formats import zcode
from skillsaw.lint_target import ZCodePluginConfigNode
from skillsaw.paths import safe_exists, safe_is_file
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.utils import read_json

from ._helpers import ZCODE_PLUGIN_REPO_TYPES


class ZCodePluginJsonValidRule(Rule):
    """Check that a ZCode plugin manifest loads"""

    since = "0.22.0"

    repo_types = ZCODE_PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "zcode-plugin-json-valid"

    @property
    def description(self) -> str:
        return "A .zcode-plugin/plugin.json must be a manifest ZCode's loader accepts"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for node in context.lint_tree.find(ZCodePluginConfigNode):
            # Only ZCode's own spelling. A Claude or Codex manifest ZCode
            # falls back to is that ecosystem's file, and its rules own it.
            if node.path.parent.name != zcode.PLUGIN_DIR_NAME or not safe_is_file(node.path):
                continue
            violations.extend(self._check_manifest(node))
        return violations

    def _check_manifest(self, node: ZCodePluginConfigNode) -> List[RuleViolation]:
        path = node.path
        data, error = read_json(path)
        if error:
            return [self.violation(f"Invalid JSON: {error}; ZCode skips this plugin", path)]
        if not isinstance(data, dict):
            return [self.violation("Manifest must be a JSON object; ZCode skips this plugin", path)]
        violations: List[RuleViolation] = []
        name = data.get("name")
        trimmed = name.strip() if isinstance(name, str) else ""
        if not zcode.NAME_RE.match(trimmed):
            violations.append(
                self.violation(
                    f"Invalid plugin name {name!r}: ZCode requires 1-128 characters of "
                    "lowercase letters, digits, '.', '_' or '-', starting with a letter or "
                    "digit; ZCode skips this plugin",
                    path,
                )
            )
        for key in zcode.UNSUPPORTED_COMPONENT_KEYS:
            if key in data:
                violations.append(
                    self.violation(
                        f"'{key}' is not loaded by ZCode; the component is ignored",
                        path,
                        severity=Severity.WARNING,
                    )
                )
        plugin_dir = node.plugin_dir
        for field in zcode.PATH_FIELDS:
            for raw in zcode.path_list(data.get(field)):
                if zcode.lexically_escapes(raw):
                    violations.append(
                        self.violation(
                            f"'{field}' path {raw!r} is absolute or leaves the plugin "
                            "directory; ZCode ignores it",
                            path,
                        )
                    )
                elif field == "hooks" and not safe_is_file(plugin_dir / raw):
                    violations.append(
                        self.violation(
                            f"'hooks' names {raw!r}, which is not a file; ZCode reports a "
                            "hooks read error and loads nothing from it",
                            path,
                        )
                    )
                elif field == "skills" and not safe_exists(plugin_dir / raw):
                    violations.append(
                        self.violation(
                            f"'skills' names {raw!r}, which does not exist",
                            path,
                            severity=Severity.WARNING,
                        )
                    )
        commands = data.get("commands")
        if isinstance(commands, dict):
            violations.extend(self._check_command_map(node, commands))
        return violations

    def _check_command_map(
        self, node: ZCodePluginConfigNode, commands: Dict[str, Any]
    ) -> List[RuleViolation]:
        """Object-form ``commands``: ``{name: {source | content, ...}}``.

        ZCode writes each entry out as a Markdown command, and skips an
        entry whose name does not normalize to a command name or that does
        not give exactly one of ``source`` and ``content``
        (``adapters/src/plugins/index.ts:716-811`` in ``zai-org/ZCode``).
        """
        violations: List[RuleViolation] = []
        for raw_name, entry in commands.items():
            label = f"Command '{raw_name}'"
            normalized = raw_name.strip().lstrip("/").lower()
            if not zcode.COMMAND_NAME_RE.match(normalized):
                violations.append(
                    self.violation(
                        f"{label}: name must be lowercase letters, digits, '_', ':' or '-' "
                        "(up to 64); ZCode skips it",
                        node.path,
                    )
                )
                continue
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(f"{label} must be an object; ZCode skips it", node.path)
                )
                continue
            source = entry.get("source") if isinstance(entry.get("source"), str) else None
            content = entry.get("content") if isinstance(entry.get("content"), str) else None
            if bool(source) == bool(content):
                violations.append(
                    self.violation(
                        f"{label} must set exactly one of 'source' and 'content'; ZCode skips it",
                        node.path,
                    )
                )
                continue
            if source:
                relative = source[2:] if source.startswith("./") else source
                if zcode.lexically_escapes(relative):
                    violations.append(
                        self.violation(
                            f"{label}: 'source' {source!r} leaves the plugin directory; "
                            "ZCode skips it",
                            node.path,
                        )
                    )
                elif not safe_is_file(node.plugin_dir / relative):
                    violations.append(
                        self.violation(
                            f"{label}: 'source' {source!r} does not exist; ZCode skips it",
                            node.path,
                        )
                    )
        return violations
