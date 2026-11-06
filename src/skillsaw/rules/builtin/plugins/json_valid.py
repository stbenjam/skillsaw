"""
Rule: plugin-json-valid
"""

import json
import re
from pathlib import Path
from typing import Iterator, List, Tuple

from skillsaw.diagnostics import safe_display
from skillsaw.paths import has_parent_traversal, is_absolute_path
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_json, read_text
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PluginNode

from ._helpers import PLUGIN_REPO_TYPES

# Manifest fields whose string values are paths to plugin components.
# `claude plugin validate` 2.1.319 checks each for '..' and existence.
_COMPONENT_PATH_FIELDS = (
    "commands",
    "agents",
    "skills",
    "hooks",
    "mcpServers",
    "outputStyles",
    "lspServers",
)

_USER_CONFIG_REF = re.compile(r"\$\{user_config\.([A-Za-z0-9_.-]+)\}")


def _component_paths(data: dict) -> Iterator[Tuple[str, str]]:
    """(field, path) for every string path a component field lists."""
    for field in _COMPONENT_PATH_FIELDS:
        value = data.get(field)
        values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        for entry in values:
            if isinstance(entry, str):
                yield field, entry


class PluginJsonValidRule(Rule):
    """Check that plugin.json is valid and has required fields"""

    repo_types = PLUGIN_REPO_TYPES

    DEFAULT_RECOMMENDED_FIELDS = ["description", "version", "author"]
    config_schema = {
        "recommended-fields": {
            "type": "list",
            "default": DEFAULT_RECOMMENDED_FIELDS,
            "description": "Fields that trigger a warning if missing from plugin.json",
        },
    }

    aliases = ("plugin-json-valid",)

    @property
    def rule_id(self) -> str:
        return "claude-plugin-json-valid"

    @property
    def description(self) -> str:
        return "plugin.json must be valid JSON with required fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        recommended_fields = self.setting("recommended-fields")
        if not isinstance(recommended_fields, list):
            recommended_fields = self.config_schema["recommended-fields"]["default"]

        for plugin_node in context.lint_tree.find(PluginNode):
            plugin_path = plugin_node.path
            plugin_json = plugin_path / ".claude-plugin" / "plugin.json"

            if not plugin_json.exists():
                continue  # Handled by plugin-json-required rule

            # Try to parse JSON
            data, error = read_json(plugin_json)
            if error:
                violations.append(self.violation(f"Invalid JSON: {error}", file_path=plugin_json))
                continue

            if not isinstance(data, dict):
                violations.append(
                    self.violation("Expected JSON object in plugin.json", file_path=plugin_json)
                )
                continue

            # Check required fields
            required_fields = ["name"]
            for field in required_fields:
                if field not in data:
                    violations.append(
                        self.violation(f"Missing required field '{field}'", file_path=plugin_json)
                    )

            # Check recommended fields (warning)
            for field in recommended_fields:
                if field not in data:
                    violations.append(
                        self.violation(
                            f"Missing recommended field '{field}'",
                            file_path=plugin_json,
                            severity=Severity.WARNING,
                        )
                    )

            # Claude's manifest reference allows arbitrary version strings;
            # the released validator checks only their type.
            if "version" in data and not isinstance(data["version"], str):
                violations.append(
                    self.violation(
                        "'version' must be a string",
                        file_path=plugin_json,
                    )
                )

            # Validate author structure
            if "author" in data:
                author = data["author"]
                if not isinstance(author, dict) or "name" not in author:
                    violations.append(
                        self.violation(
                            "Author must be an object with 'name' field",
                            file_path=plugin_json,
                        )
                    )

            violations.extend(self._check_component_paths(data, plugin_path, plugin_json))
            violations.extend(self._check_user_config_refs(data, plugin_path, plugin_json))

        return violations

    def _check_component_paths(
        self, data: dict, plugin_path: Path, plugin_json: Path
    ) -> List[RuleViolation]:
        """A component path outside the plugin or missing fails to load."""
        violations = []
        for field, entry in _component_paths(data):
            shown = safe_display(entry)
            if is_absolute_path(entry) or has_parent_traversal(entry):
                message = (
                    f"'{field}' path '{shown}' leaves the plugin directory — "
                    "Claude Code does not load it"
                )
            elif not (plugin_path / entry).exists():
                message = (
                    f"'{field}' path '{shown}' does not exist — Claude Code "
                    "reports a load failure"
                )
            else:
                continue
            violations.append(self.violation(message, file_path=plugin_json))
        return violations

    def _check_user_config_refs(
        self, data: dict, plugin_path: Path, plugin_json: Path
    ) -> List[RuleViolation]:
        """An MCP server that reads an undeclared user_config key is dropped.

        Reads the inline ``mcpServers`` map and the plugin's ``.mcp.json``,
        the two places servers are declared in nearly every plugin.
        """
        declared = data.get("userConfig")
        declared = set(declared) if isinstance(declared, dict) else set()
        sources = []
        if isinstance(data.get("mcpServers"), dict):
            sources.append((plugin_json, json.dumps(data["mcpServers"])))
        mcp_json = plugin_path / ".mcp.json"
        text = read_text(mcp_json) if mcp_json.is_file() else None
        if text:
            sources.append((mcp_json, text))

        violations = []
        for path, text in sources:
            if "user_config" not in text:
                continue
            missing = sorted(set(_USER_CONFIG_REF.findall(text)) - declared)
            if missing:
                keys = ", ".join(f"'{key}'" for key in missing)
                violations.append(
                    self.violation(
                        f"MCP configuration references user_config {keys}, which "
                        "plugin.json does not declare under 'userConfig' — Claude Code "
                        "cannot resolve it on a fresh install and drops the server",
                        file_path=path,
                    )
                )
        return violations
