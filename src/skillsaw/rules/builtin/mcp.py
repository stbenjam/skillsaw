"""
Rules for validating MCP (Model Context Protocol) configuration
"""

from typing import List, Dict, Any
from pathlib import Path

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PluginNode
from skillsaw.rules.builtin.content_analysis import McpBlock
from skillsaw.rules.builtin.utils import read_json


class McpValidJsonRule(Rule):
    """Check that MCP configuration is valid JSON with proper structure"""

    VALID_MCP_TYPES = ("stdio", "http", "sse")
    REQUIRED_FIELDS_BY_TYPE = {"stdio": "command", "http": "url", "sse": "url"}

    @property
    def rule_id(self) -> str:
        return "mcp-valid-json"

    @property
    def description(self) -> str:
        return "MCP configuration must be valid JSON with proper mcpServers structure"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for block in context.lint_tree.find(McpBlock):
            if block.parse_error:
                violations.append(
                    self.violation(f"Invalid JSON: {block.parse_error}", file_path=block.path)
                )
                continue

            data = block.raw_data
            if data is None:
                violations.append(
                    self.violation("MCP configuration must be a JSON object", file_path=block.path)
                )
                continue

            if "mcpServers" in data:
                violations.extend(self._validate_mcp_structure(data, block.path))
            else:
                violations.extend(self._validate_mcp_structure({"mcpServers": data}, block.path))

        # Also check mcpServers embedded in plugin.json (not a separate file node)
        for plugin_node in context.lint_tree.find(PluginNode):
            plugin_json_path = plugin_node.path / ".claude-plugin" / "plugin.json"
            if plugin_json_path.exists():
                violations.extend(self._validate_plugin_json_mcp(plugin_json_path))

        return violations

    def _validate_plugin_json_mcp(self, plugin_json: Path) -> List[RuleViolation]:
        """Validate mcpServers field in plugin.json"""
        violations = []

        data, error = read_json(plugin_json)
        if error:
            return violations

        if not isinstance(data, dict):
            return violations

        if "mcpServers" not in data:
            return violations

        mcp_config = {"mcpServers": data["mcpServers"]}
        violations.extend(self._validate_mcp_structure(mcp_config, plugin_json))

        return violations

    def _validate_mcp_structure(self, data: Dict[str, Any], file_path: Path) -> List[RuleViolation]:
        """Validate MCP configuration structure"""
        violations = []

        if not isinstance(data, dict):
            violations.append(
                self.violation("MCP configuration must be a JSON object", file_path=file_path)
            )
            return violations

        if "mcpServers" not in data:
            violations.append(
                self.violation(
                    "MCP configuration must contain 'mcpServers' key",
                    file_path=file_path,
                )
            )
            return violations

        mcp_servers = data["mcpServers"]
        if not isinstance(mcp_servers, dict):
            violations.append(
                self.violation("'mcpServers' must be a JSON object", file_path=file_path)
            )
            return violations

        for server_name, server_config in mcp_servers.items():
            if not isinstance(server_config, dict):
                violations.append(
                    self.violation(
                        f"MCP server '{server_name}' configuration must be an object",
                        file_path=file_path,
                    )
                )
                continue

            if server_name == "workspace":
                violations.append(
                    self.violation(
                        f"MCP server name 'workspace' is reserved",
                        file_path=file_path,
                        severity=Severity.WARNING,
                    )
                )

            server_type = server_config.get("type", "stdio")

            if server_type not in self.VALID_MCP_TYPES:
                violations.append(
                    self.violation(
                        f"MCP server '{server_name}' has invalid type '{server_type}'. Must be one of: {', '.join(self.VALID_MCP_TYPES)}",
                        file_path=file_path,
                    )
                )
            else:
                required_field = self.REQUIRED_FIELDS_BY_TYPE[server_type]
                if required_field not in server_config:
                    violations.append(
                        self.violation(
                            f"MCP server '{server_name}' with type '{server_type}' must have a '{required_field}' field",
                            file_path=file_path,
                        )
                    )

            if "args" in server_config and not isinstance(server_config["args"], list):
                violations.append(
                    self.violation(
                        f"MCP server '{server_name}' 'args' must be an array",
                        file_path=file_path,
                    )
                )

            if "env" in server_config and not isinstance(server_config["env"], dict):
                violations.append(
                    self.violation(
                        f"MCP server '{server_name}' 'env' must be an object",
                        file_path=file_path,
                    )
                )

            if "cwd" in server_config and not isinstance(server_config["cwd"], str):
                violations.append(
                    self.violation(
                        f"MCP server '{server_name}' 'cwd' must be a string",
                        file_path=file_path,
                    )
                )

            if "url" in server_config and not isinstance(server_config["url"], str):
                violations.append(
                    self.violation(
                        f"MCP server '{server_name}' 'url' must be a string",
                        file_path=file_path,
                    )
                )

            if "headers" in server_config and not isinstance(server_config["headers"], dict):
                violations.append(
                    self.violation(
                        f"MCP server '{server_name}' 'headers' must be an object",
                        file_path=file_path,
                    )
                )

            if "startupTimeout" in server_config:
                val = server_config["startupTimeout"]
                is_valid_number = isinstance(val, (int, float)) and not isinstance(val, bool)
                if not is_valid_number:
                    violations.append(
                        self.violation(
                            f"MCP server '{server_name}' 'startupTimeout' must be a number",
                            file_path=file_path,
                        )
                    )

            if "headersHelper" in server_config and not isinstance(
                server_config["headersHelper"], str
            ):
                violations.append(
                    self.violation(
                        f"MCP server '{server_name}' 'headersHelper' must be a string",
                        file_path=file_path,
                    )
                )

            if "alwaysLoad" in server_config:
                val = server_config["alwaysLoad"]
                if not isinstance(val, bool):
                    violations.append(
                        self.violation(
                            f"MCP server '{server_name}' 'alwaysLoad' must be a boolean",
                            file_path=file_path,
                        )
                    )

            if "oauth" in server_config:
                oauth = server_config["oauth"]
                if not isinstance(oauth, dict):
                    violations.append(
                        self.violation(
                            f"MCP server '{server_name}' 'oauth' must be an object",
                            file_path=file_path,
                        )
                    )

        return violations


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
