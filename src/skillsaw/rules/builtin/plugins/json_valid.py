"""
Rule: plugin-json-valid
"""

import json
import re
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from skillsaw.blocks import McpBlock
from skillsaw.diagnostics import safe_display
from skillsaw.discovery.claude import claude_declared_mcp_files
from skillsaw.paths import has_parent_traversal, is_absolute_path, safe_exists
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_json
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

# How many undeclared keys one finding names before summarizing the rest.
_MAX_KEYS_SHOWN = 5

_USER_CONFIG_REF = re.compile(r"\$\{user_config\.([A-Za-z0-9_.-]+)\}")


# The server fields Claude Code substitutes ``${user_config.KEY}`` into;
# a reference anywhere else is never resolved, so never checked.
_USER_CONFIG_FIELDS = ("command", "args", "env", "url", "headers")


def _server_map(payload) -> dict:
    """The server map in a ``{"mcpServers": {...}}`` document or a bare map."""
    servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    if not isinstance(servers, dict):
        servers = payload if isinstance(payload, dict) else {}
    return servers


def _declared_keys(options) -> set:
    """Option keys a ``userConfig`` map declares; Claude Code rejects a non-object option."""
    if not isinstance(options, dict):
        return set()
    return {key for key, option in options.items() if isinstance(option, dict)}


def _channel_keys(data: dict) -> dict:
    """Server name -> user_config keys its top-level ``channels`` entries declare."""
    keys: dict = {}
    channels = data.get("channels")
    for channel in channels if isinstance(channels, list) else ():
        if isinstance(channel, dict) and isinstance(channel.get("server"), str):
            keys.setdefault(channel["server"], set()).update(
                _declared_keys(channel.get("userConfig"))
            )
    return keys


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

        # MCP documents in the lint tree by resolved path. The tree holds
        # only contained, non-excluded files, so this never reads outside it.
        mcp_by_path: Dict[Path, McpBlock] = {}
        for block in context.lint_tree.find(McpBlock):
            resolved = context.resolve_path(block.path)
            if resolved is not None and block.raw_data:
                mcp_by_path.setdefault(resolved, block)

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

            if "name" in data and not isinstance(data["name"], str):
                violations.append(self.violation("'name' must be a string", file_path=plugin_json))

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
            # The files Claude Code reads servers from, matched by path: the
            # block class says which host's rules apply, not which file this is.
            claude_mcp = [plugin_path / ".mcp.json", *claude_declared_mcp_files(plugin_path)]
            resolved_mcp = dict.fromkeys(context.resolve_path(path) for path in claude_mcp)
            owned = [mcp_by_path[path] for path in resolved_mcp if path in mcp_by_path]
            violations.extend(self._check_user_config_refs(data, owned, plugin_json))

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
            elif not safe_exists(plugin_path / entry):
                message = (
                    f"'{field}' path '{shown}' does not exist — Claude Code "
                    "reports a load failure"
                )
            else:
                continue
            violations.append(self.violation(message, file_path=plugin_json))
        return violations

    def _check_user_config_refs(
        self, data: dict, mcp_blocks: List[McpBlock], plugin_json: Path
    ) -> List[RuleViolation]:
        """An MCP server that reads an undeclared user_config key is dropped.

        Reads the inline ``mcpServers`` map and the plugin's MCP files from
        the lint tree, so excluded or escaping files are never read.
        """
        declared = _declared_keys(data.get("userConfig"))
        channel_keys = _channel_keys(data)
        # The inline map is already a server map; only files may wrap theirs.
        sources = []
        if isinstance(data.get("mcpServers"), dict):
            sources.append((plugin_json, data["mcpServers"]))
        sources.extend((block.path, _server_map(block.raw_data)) for block in mcp_blocks)

        violations = []
        for path, servers in sources:
            missing = set()
            for name, server in servers.items():
                if not isinstance(server, dict):
                    continue
                helper = server.get("headersHelper")
                if isinstance(helper, str) and _USER_CONFIG_REF.search(helper):
                    violations.append(
                        self.violation(
                            f"MCP server '{safe_display(name)}' references user_config in "
                            "'headersHelper' — Claude Code never substitutes it there (the "
                            "value would reach a shell); read the value inside the helper, "
                            "for example from the server's 'env'",
                            file_path=path,
                        )
                    )
                text = json.dumps([server.get(field) for field in _USER_CONFIG_FIELDS])
                if "user_config" not in text:
                    continue
                allowed = declared | channel_keys.get(name, set())
                missing.update(set(_USER_CONFIG_REF.findall(text)) - allowed)
            if not missing:
                continue
            missing = sorted(missing)
            keys = ", ".join(f"'{safe_display(key)}'" for key in missing[:_MAX_KEYS_SHOWN])
            if len(missing) > _MAX_KEYS_SHOWN:
                keys += f" and {len(missing) - _MAX_KEYS_SHOWN} more"
            violations.append(
                self.violation(
                    f"MCP configuration references user_config {keys}, which "
                    "plugin.json does not declare under 'userConfig' or in the 'userConfig' "
                    "of a top-level 'channels' entry naming the server — Claude Code "
                    "cannot resolve it on a fresh install and drops the server",
                    file_path=path,
                )
            )
        return violations
