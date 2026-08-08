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


#: Fields that appear on one server, never on a map of them.
_SERVER_FIELDS = frozenset({"command", "url", "type", "args", "env", "headers"})


def _looks_like_server_map(value: Any) -> bool:
    """Whether *value* reads as a map of servers rather than one server.

    Used only to disambiguate a key named ``servers`` in a file that also
    accepts a bare server map, where the name alone cannot say whether it
    is VS Code's wrapper or a server someone named ``servers``.
    """
    if not isinstance(value, dict) or not value:
        return False
    if _SERVER_FIELDS & set(value):
        return False
    return all(isinstance(entry, dict) for entry in value.values())


class McpValidJsonRule(Rule):
    """Check that MCP configuration is valid JSON with proper structure"""

    default_enabled = True

    VALID_MCP_TYPES = ("stdio", "http", "sse", "streamable-http", "ws")

    # Every spelling of the server-map wrapper across hosts. Used to tell
    # "this file names its servers under another host's key" apart from
    # "this file declares no servers".
    FOREIGN_SERVER_KEYS = frozenset({"mcpServers", "servers"})
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
            # Hosts spell the wrapper key differently (VS Code uses
            # ``servers``); the block knows its own.
            servers_key = block.servers_key
            wrong_keys = sorted(
                key
                for key in self.FOREIGN_SERVER_KEYS & set(data) - {servers_key}
                # In a file that accepts a bare map, a key named "servers"
                # is ambiguous: it is either another host's wrapper or a
                # server that happens to be called that. Nothing forbids the
                # name, so the value decides — a wrapper holds server
                # objects, a server holds connection fields.
                if not block.allow_bare_server_map or _looks_like_server_map(data[key])
            )
            if servers_key in data:
                payload: Any = data[servers_key]
            elif wrong_keys:
                # Another host's wrapper key: the servers are really there,
                # this host just will not find them. Checked before the
                # bare-map fallback, which would otherwise read the wrapper
                # itself as a server named "servers".
                violations.append(
                    self.violation(
                        f"MCP configuration uses '{wrong_keys[0]}' but this host reads "
                        f"'{servers_key}' — the servers are not loaded",
                        file_path=block.path,
                    )
                )
                continue
            elif block.allow_bare_server_map:
                # The Claude-family files may be written as a bare map.
                payload = data
            elif data and block.non_server_keys.isdisjoint(data):
                # Every key is unaccounted for and this host has no
                # bare-map form, so the author wrote servers the host will
                # not load. VS Code is the exception the check reads around:
                # an ``inputs``/``sandbox``-only file declares no servers on
                # purpose and is complete as written.
                violations.append(
                    self.violation(
                        f"MCP configuration has no '{servers_key}' key — " "no servers are loaded",
                        file_path=block.path,
                    )
                )
                continue
            else:
                # Nothing to validate: the file declares no servers, and
                # what it does declare is not a server map.
                continue
            violations.extend(
                self._validate_mcp_structure(
                    {"mcpServers": payload},
                    block.path,
                    require_usable=require_usable,
                    servers_key=servers_key,
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
        servers_key: str = "mcpServers",
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
                    f"MCP configuration must contain '{servers_key}' key",
                    file_path=file_path,
                )
            )
            return violations

        mcp_servers = data["mcpServers"]
        if not isinstance(mcp_servers, dict):
            violations.append(
                self.violation(f"'{servers_key}' must be a JSON object", file_path=file_path)
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

            # Transport is only inferred when the server does not say. Every
            # host infers it from the connection field, so a remote server
            # written as ``{"url": "..."}`` — the most common remote form —
            # is not a stdio server missing its ``command``. An explicit
            # ``"type": null`` is a stated wrong answer, not silence: it
            # falls through to the enum check below and is reported.
            if "type" not in server_config:
                if "url" in server_config and "command" not in server_config:
                    server_type = "http"
                else:
                    server_type = "stdio"
            else:
                server_type = server_config["type"]

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
