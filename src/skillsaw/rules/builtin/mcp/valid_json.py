"""
Rule: mcp-valid-json
"""

from typing import List, Dict, Any
from pathlib import Path

from skillsaw.blocks import AgentPluginMcpBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.lint_target import PluginNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import McpBlock
from skillsaw.rules.builtin.utils import read_json


def _is_usable(value: Any) -> bool:
    """Whether a required connection field names something spawnable."""
    return isinstance(value, str) and bool(value.strip())


class McpValidJsonRule(Rule):
    """Check that MCP configuration is valid JSON with proper structure"""

    default_enabled = True

    VALID_MCP_TYPES = ("stdio", "http", "sse", "streamable-http", "ws")
    REQUIRED_FIELDS_BY_TYPE = {
        "stdio": "command",
        "http": "url",
        "sse": "url",
        "streamable-http": "url",
        "ws": "url",
    }

    # Server names reserved for Claude Code's built-in servers. A user
    # server that shadows one of these is ignored, so warn on it. See
    # the Claude Code MCP docs (code.claude.com/docs/en/mcp).
    RESERVED_SERVER_NAMES = (
        "workspace",
        "claude-in-chrome",
        "computer-use",
        "Claude Preview",
        "Claude Browser",
    )

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
            # Agent Plugins uses a closed, versioned schema with different
            # defaults and failure boundaries. Its dedicated rule validates
            # this block; running the permissive Claude/Codex shape check too
            # would duplicate findings and accept fields the portable format
            # rejects. Policy rules still see the McpBlock subclass.
            #
            # Defer only when that dedicated rule can actually run: the tree
            # role is deliberately --type-invariant, but agent-plugin-mcp-valid
            # is gated on RepositoryType.AGENT_PLUGIN, so under a forced
            # non-agent ``--type`` an unconditional skip would leave the file
            # validated by no rule at all.
            if (
                isinstance(block, AgentPluginMcpBlock)
                and RepositoryType.AGENT_PLUGIN in context.repo_types
            ):
                continue
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

            # Conditional strictness, not a skip: the tightened
            # non-empty-string checks apply only inside Codex-ONLY plugins,
            # so dual-manifest plugins keep their established Claude results.
            require_usable = context.in_codex_only_plugin(block.path)
            if "mcpServers" in data:
                violations.extend(
                    self._validate_mcp_structure(data, block.path, require_usable=require_usable)
                )
            else:
                violations.extend(
                    self._validate_mcp_structure(
                        {"mcpServers": data},
                        block.path,
                        require_usable=require_usable,
                    )
                )

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

        mcp_servers_value = data["mcpServers"]

        # mcpServers can be a string (file path reference) or array per the
        # Claude Code plugin spec — accept those forms without further
        # structural validation.
        if isinstance(mcp_servers_value, (str, list)):
            return violations

        mcp_config = {"mcpServers": mcp_servers_value}
        violations.extend(self._validate_mcp_structure(mcp_config, plugin_json))

        return violations

    def _validate_mcp_structure(
        self,
        data: Dict[str, Any],
        file_path: Path,
        *,
        require_usable: bool = False,
    ) -> List[RuleViolation]:
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

            if server_name in self.RESERVED_SERVER_NAMES:
                violations.append(
                    self.violation(
                        f"MCP server name '{server_name}' is reserved "
                        f"for a Claude Code built-in server",
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
                # Present is not the same as usable: ``"command": []`` and
                # ``"command": ""`` satisfy a key-existence check while
                # naming nothing the host can spawn. A non-string ``url``
                # is left to the dedicated check below, so one defect
                # still yields one violation.
                elif (
                    require_usable
                    and not _is_usable(server_config[required_field])
                    and not (required_field == "url" and not isinstance(server_config["url"], str))
                ):
                    violations.append(
                        self.violation(
                            f"MCP server '{safe_display(server_name)}' '{required_field}' "
                            "must be a non-empty string",
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

            for timeout_field in ("startupTimeout", "timeout"):
                if timeout_field in server_config:
                    val = server_config[timeout_field]
                    is_valid_number = isinstance(val, (int, float)) and not isinstance(val, bool)
                    if not is_valid_number:
                        violations.append(
                            self.violation(
                                f"MCP server '{server_name}' '{timeout_field}' must be a number",
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
