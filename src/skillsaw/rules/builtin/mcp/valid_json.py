"""
Rule: mcp-valid-json
"""

from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from pathlib import Path

from skillsaw.blocks import (
    AgentPluginMcpBlock,
    CopilotAgentMcpBlock,
    McpConfigRole,
    OpenCodeMcpBlock,
)
from skillsaw.context import HAS_OPENCODE, RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.utils import is_finite_number
from skillsaw.lint_target import PluginNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.secret_detection import (
    mapped_secret_description,
    placeholder_markers,
    url_has_userinfo,
)
from skillsaw.rules.builtin.utils import read_json


def _is_usable(value: Any) -> bool:
    """Whether a required connection field names something spawnable."""
    return isinstance(value, str) and bool(value.strip())


def _yaml_type_name(value: Any) -> str:
    """Stable schema type name without rendering a composite YAML value."""
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "mapping"
    return type(value).__name__


#: How a per-server credential map is named in a finding, keyed by the map's
#: own key so each host's spelling reads naturally. The fallback covers the
#: two maps this rule reads directly.
_CREDENTIAL_MAP_LABELS = {
    "env": "environment variable",
    "environment": "environment variable",
    "headers": "HTTP header",
    "oauth": "OAuth field",
}

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
    surface_dependencies = ("copilot-agent-valid",)

    # Mirrors ``agent-plugin-mcp-valid`` and ``content-embedded-secrets``: a
    # project that allowlisted its own placeholder convention must not be told
    # its mcp.json embeds a credential for the same value.
    config_schema = {
        "additional-placeholders": {
            "type": "list",
            "default": [],
            "description": (
                "Extra case-insensitive substrings that mark a generic "
                "credential value as a placeholder (suppressing the violation)"
            ),
        },
    }

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
        return "MCP configuration must use valid syntax and a host-readable server structure"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for block in self.dependency_scoped_find(context, McpConfigRole):
            # This tree role exists so the format rule and shared MCP rules
            # can read one parsed payload. When a version pin disables the
            # format rule that introduced the surface, keep the established
            # rule set unchanged rather than leaking a new MCP diagnostic.
            if isinstance(block, CopilotAgentMcpBlock) and not self.surface_rule_enabled(
                "copilot-agent-valid"
            ):
                continue
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
            # OpenCode's dialect shares the idea of an MCP server and almost
            # none of the spelling: transports are named for where the server
            # runs (``local``/``remote``) rather than for the wire protocol,
            # a local ``command`` is an argv array, the environment map is
            # ``environment``, and v2 splits ``timeout`` into an object.
            # Every *shape* check below would report a correctly written
            # OpenCode config as invalid, so ``opencode-config-valid``
            # validates the shape instead.
            #
            # The deferral is narrower than the one above. Unlike the
            # ``--type`` gate, nothing here can see whether
            # ``opencode-config-valid`` is *enabled*, and it carries
            # ``since = "0.20.0"`` — so a project whose ``.skillsaw.yaml``
            # still pins an older ``version:``, the ordinary state right
            # after an upgrade, has it gated off while this rule defers.
            # Everything that holds whatever dialect the file is written in
            # therefore stays here, where no version gate can reach it; see
            # ``_dialect_neutral_violations``. Policy rules are unaffected —
            # they read ``server_names``, which the block normalizes.
            if isinstance(block, OpenCodeMcpBlock) and HAS_OPENCODE in context.detected_formats:
                violations.extend(self._dialect_neutral_violations(block))
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
            require_usable = block.require_usable_connection or context.in_codex_only_plugin(
                block.path
            )
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
                # Both wrappers present: the host reads its own, so the
                # servers under the other one are silently not loaded. That
                # is the whole point of the diagnostic, and it does not stop
                # being true because the expected key also exists.
                for wrong in wrong_keys:
                    if data[wrong]:
                        violations.append(
                            self.violation(
                                f"MCP configuration also has '{wrong}' — this host reads "
                                f"'{servers_key}', so those servers are not loaded",
                                file_path=block.path,
                            )
                        )
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
            elif data and not set(data) <= (block.non_server_keys | block.always_ignored_keys):
                # Some key is unaccounted for and this host has no bare-map
                # form, so the author wrote servers the host will not load.
                # Only a file whose keys are *all* documented siblings —
                # VS Code's ``inputs``/``sandbox`` — declares no servers on
                # purpose and is complete as written. Testing for any such
                # sibling instead would let one ``inputs`` key wave through
                # an unwrapped server sitting beside it.
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
                    check_reserved=block.claude_builtins_reserved,
                    type_aliases=block.type_aliases,
                    line=getattr(block, "source_line", None),
                    line_for=getattr(block, "source_line_for", None),
                )
            )

        # Also check mcpServers embedded in plugin.json (not a separate file node)
        for plugin_node in self.dependency_scoped_find(context, PluginNode):
            plugin_json_path = plugin_node.path / ".claude-plugin" / "plugin.json"
            if plugin_json_path.exists():
                violations.extend(self._validate_plugin_json_mcp(plugin_json_path))

        return violations

    def _dialect_neutral_violations(self, block: McpConfigRole) -> List[RuleViolation]:
        """The checks this rule keeps for a block whose *shape* it defers.

        Not the whole rule, and not one check either: what stays is
        everything that does not depend on the host's spelling. A document
        that is not JSON is unreadable to every host. A ``url`` carrying
        user information is the same defect in every dialect. So is a
        credential sitting in a per-server map — the map's *name* differs
        between hosts, which is why the block declares it in
        :attr:`McpBlock.credential_maps` rather than this rule naming it.

        Keeping them here rather than in the deferring rule is what makes
        them survive a ``.skillsaw.yaml`` pinning a ``version:`` older than
        that rule's ``since``, which is the ordinary state right after an
        upgrade.

        The line stops at what the *document* must be. That an OpenCode
        config's top level is an object is a claim about OpenCode's own
        schema, not about JSON or about MCP, so it stays with the rule that
        knows the dialect.
        """
        violations: List[RuleViolation] = []
        if block.parse_error:
            return [self.violation(f"Invalid JSON: {block.parse_error}", file_path=block.path)]
        for name, server in block.server_entries():
            if not isinstance(server, dict):
                continue
            shown = safe_display(str(name))
            url = server.get("url")
            if isinstance(url, str) and url_has_userinfo(url):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' 'url' must not contain user information",
                        file_path=block.path,
                    )
                )
            for key, header in block.credential_maps:
                values = server.get(key)
                if not isinstance(values, dict):
                    continue
                violations.extend(
                    self._mapped_secret_violations(
                        values,
                        server_name=shown,
                        file_path=block.path,
                        header=header,
                        aliases=block.credential_key_aliases,
                        location=key,
                    )
                )
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
        check_reserved: bool = True,
        type_aliases: Mapping[str, str] = MappingProxyType({}),
        line: Optional[int] = None,
        line_for: Optional[Callable[[Any, Any], Optional[int]]] = None,
    ) -> List[RuleViolation]:
        """Validate MCP configuration structure"""
        violations = []

        def report(
            message: str, *, node: Any = None, key: Any = None, **kwargs: Any
        ) -> RuleViolation:
            """Create a finding at the embedded field when one exists."""
            resolved_line = (
                line_for(node, key) if line_for is not None and node is not None else line
            )
            return self.violation(message, file_path=file_path, line=resolved_line, **kwargs)

        if not isinstance(data, dict):
            violations.append(report("MCP configuration must be a JSON object"))
            return violations

        if "mcpServers" not in data:
            violations.append(report(f"MCP configuration must contain '{servers_key}' key"))
            return violations

        mcp_servers = data["mcpServers"]
        if not isinstance(mcp_servers, dict):
            violations.append(report(f"'{servers_key}' must be a JSON object"))
            return violations

        for server_name, server_config in mcp_servers.items():
            # Sanitized once, used by every message below. A server name is
            # author-controlled text that lands in terminal output, JSON and
            # SARIF, so it gets the same treatment as any other echoed
            # manifest value: userinfo redacted, control characters and lone
            # surrogates replaced. Bound at the top of the loop rather than
            # per message so a diagnostic added later cannot forget it.
            shown = safe_display(str(server_name))
            if not isinstance(server_name, str):
                violations.append(
                    report(
                        f"MCP server name '{shown}' must be a string",
                        node=mcp_servers,
                        key=server_name,
                    )
                )
            if not isinstance(server_config, dict):
                violations.append(
                    report(
                        f"MCP server '{shown}' configuration must be an object",
                        node=mcp_servers,
                        key=server_name,
                    )
                )
                continue

            if (
                check_reserved
                and isinstance(server_name, str)
                and server_name in self.RESERVED_SERVER_NAMES
            ):
                violations.append(
                    report(
                        f"MCP server name '{shown}' is reserved "
                        f"for a Claude Code built-in server",
                        node=mcp_servers,
                        key=server_name,
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

            normalized_type = (
                type_aliases.get(server_type, server_type)
                if isinstance(server_type, str)
                else server_type
            )
            valid_type_names = (*self.VALID_MCP_TYPES, *type_aliases)
            if normalized_type not in self.VALID_MCP_TYPES:
                # Embedded YAML can put an exponentially expanding alias graph
                # here. Never materialize a non-string merely to truncate the
                # result; its Python/YAML shape is the actionable diagnosis.
                shown_type = (
                    safe_display(server_type)
                    if isinstance(server_type, str)
                    else _yaml_type_name(server_type)
                )
                violations.append(
                    report(
                        f"MCP server '{shown}' has invalid type "
                        f"'{shown_type}'. Must be one of: "
                        f"{', '.join(valid_type_names)}",
                        node=server_config,
                        key="type",
                    )
                )
            else:
                required_field = self.REQUIRED_FIELDS_BY_TYPE[normalized_type]
                if required_field not in server_config:
                    violations.append(
                        report(
                            f"MCP server '{shown}' with type "
                            f"'{safe_display(server_type)}' must have a "
                            f"'{required_field}' field",
                            node=mcp_servers,
                            key=server_name,
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
                        report(
                            f"MCP server '{shown}' '{required_field}' "
                            "must be a non-empty string",
                            node=server_config,
                            key=required_field,
                        )
                    )

            if "args" in server_config and not isinstance(server_config["args"], list):
                violations.append(
                    report(
                        f"MCP server '{shown}' 'args' must be an array",
                        node=server_config,
                        key="args",
                    )
                )

            if "env" in server_config and not isinstance(server_config["env"], dict):
                violations.append(
                    report(
                        f"MCP server '{shown}' 'env' must be an object",
                        node=server_config,
                        key="env",
                    )
                )
            elif isinstance(server_config.get("env"), dict):
                violations.extend(
                    self._mapped_secret_violations(
                        server_config["env"],
                        server_name=shown,
                        file_path=file_path,
                        header=False,
                        line=line,
                        line_for=line_for,
                    )
                )

            if "cwd" in server_config and not isinstance(server_config["cwd"], str):
                violations.append(
                    report(
                        f"MCP server '{shown}' 'cwd' must be a string",
                        node=server_config,
                        key="cwd",
                    )
                )

            if "url" in server_config and not isinstance(server_config["url"], str):
                violations.append(
                    report(
                        f"MCP server '{shown}' 'url' must be a string",
                        node=server_config,
                        key="url",
                    )
                )
            elif isinstance(server_config.get("url"), str):
                if url_has_userinfo(server_config["url"]):
                    violations.append(
                        report(
                            f"MCP server '{shown}' 'url' must not contain user information",
                            node=server_config,
                            key="url",
                        )
                    )

            if "headers" in server_config and not isinstance(server_config["headers"], dict):
                violations.append(
                    report(
                        f"MCP server '{shown}' 'headers' must be an object",
                        node=server_config,
                        key="headers",
                    )
                )
            elif isinstance(server_config.get("headers"), dict):
                violations.extend(
                    self._mapped_secret_violations(
                        server_config["headers"],
                        server_name=shown,
                        file_path=file_path,
                        header=True,
                        line=line,
                        line_for=line_for,
                    )
                )

            for timeout_field in ("startupTimeout", "timeout"):
                if timeout_field in server_config:
                    val = server_config[timeout_field]
                    # NaN/Infinity (which Python's json accepts and strict
                    # JSON does not) and bools are rejected; a huge integer
                    # literal is answered without a float conversion that
                    # would raise OverflowError and kill the rule.
                    is_valid_number = is_finite_number(val)
                    if not is_valid_number:
                        violations.append(
                            report(
                                f"MCP server '{shown}' '{timeout_field}' must be a number",
                                node=server_config,
                                key=timeout_field,
                            )
                        )

            if "headersHelper" in server_config and not isinstance(
                server_config["headersHelper"], str
            ):
                violations.append(
                    report(
                        f"MCP server '{shown}' 'headersHelper' must be a string",
                        node=server_config,
                        key="headersHelper",
                    )
                )

            if "alwaysLoad" in server_config:
                val = server_config["alwaysLoad"]
                if not isinstance(val, bool):
                    violations.append(
                        report(
                            f"MCP server '{shown}' 'alwaysLoad' must be a boolean",
                            node=server_config,
                            key="alwaysLoad",
                        )
                    )

            if "oauth" in server_config:
                oauth = server_config["oauth"]
                if not isinstance(oauth, dict):
                    violations.append(
                        report(
                            f"MCP server '{shown}' 'oauth' must be an object",
                            node=server_config,
                            key="oauth",
                        )
                    )

        return violations

    def _placeholder_markers(self) -> Tuple[str, ...]:
        """The placeholder allowlist, extended by this rule's configuration."""
        return placeholder_markers(self.config.get("additional-placeholders", []))

    def _mapped_secret_violations(
        self,
        values: Dict[Any, Any],
        *,
        server_name: str,
        file_path: Path,
        header: bool,
        aliases: Mapping[str, str] = MappingProxyType({}),
        location: str = "",
        line: Optional[int] = None,
        line_for: Optional[Callable[[Any, Any], Optional[int]]] = None,
    ) -> List[RuleViolation]:
        """Report structured credentials without copying their values.

        *aliases* normalizes a key before the credential-*name* test only —
        a host whose older spelling the shared detector cannot split needs
        it — while the message always names the key as the author wrote it.
        *location* names the map for the message when it is not one of the
        two this rule reads directly.
        """
        violations = []
        where = _CREDENTIAL_MAP_LABELS.get(
            location, "HTTP header" if header else "environment variable"
        )
        for name, value in values.items():
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            description = mapped_secret_description(
                aliases.get(name, name),
                value,
                header=header,
                markers=self._placeholder_markers(),
            )
            if description is None:
                continue
            violations.append(
                self.violation(
                    f"MCP server '{server_name}' {where} "
                    f"'{safe_display(name)}' embeds {description}; use a placeholder "
                    "or environment substitution instead of a credential value",
                    file_path=file_path,
                    line=line_for(values, name) if line_for is not None else line,
                )
            )
        return violations
