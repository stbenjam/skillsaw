"""
Rule: mcp-prohibited
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PluginNode
from skillsaw.rules.builtin.content_analysis import McpBlock
from skillsaw.rules.builtin.utils import read_json


class McpProhibitedRule(Rule):
    """Check that plugins do not enable MCP servers (security/policy rule)"""

    config_schema = {
        "allowlist": {
            "type": "list",
            "default": [],
            "description": "MCP server names that are permitted",
        },
    }

    @property
    def rule_id(self) -> str:
        return "mcp-prohibited"

    @property
    def description(self) -> str:
        return "Plugins should not enable non-allowlisted MCP servers"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        allowlist = set(self.config.get("allowlist", []))

        for block in context.lint_tree.find(McpBlock):
            prohibited = block.server_names - allowlist if allowlist else block.server_names
            if not prohibited:
                continue
            if allowlist:
                violations.append(
                    self.violation(
                        f"Plugin defines non-allowlisted MCP servers: {', '.join(sorted(prohibited))}",
                        file_path=block.path,
                    )
                )
            else:
                violations.append(
                    self.violation(
                        "Plugin defines MCP servers in .mcp.json",
                        file_path=block.path,
                    )
                )

        # Also check mcpServers embedded in plugin.json
        for plugin_node in context.lint_tree.find(PluginNode):
            plugin_json_path = plugin_node.path / ".claude-plugin" / "plugin.json"
            if not plugin_json_path.exists():
                continue
            data, error = read_json(plugin_json_path)
            if error or not isinstance(data, dict):
                continue
            if "mcpServers" not in data:
                continue
            mcp_servers = data["mcpServers"]
            if not isinstance(mcp_servers, dict):
                continue
            server_names = set(mcp_servers.keys())
            prohibited = server_names - allowlist if allowlist else server_names
            if not prohibited:
                continue
            if allowlist:
                violations.append(
                    self.violation(
                        f"Plugin defines non-allowlisted MCP servers: {', '.join(sorted(prohibited))}",
                        file_path=plugin_json_path,
                    )
                )
            else:
                violations.append(
                    self.violation(
                        "Plugin defines MCP servers in plugin.json",
                        file_path=plugin_json_path,
                    )
                )

        return violations
