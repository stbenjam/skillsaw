"""
Rule: mcp-valid-json
"""

import re
from typing import List, Dict, Any, Tuple
from pathlib import Path
from urllib.parse import urlsplit

from skillsaw.blocks import AgentPluginMcpBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.utils import is_finite_number
from skillsaw.lint_target import PluginNode
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import McpBlock
from skillsaw.rules.builtin.secret_detection import (
    DEFAULT_PLACEHOLDER_MARKERS,
    mapped_secret_description,
)
from skillsaw.rules.builtin.utils import read_json


def _is_usable(value: Any) -> bool:
    """Whether a required connection field names something spawnable."""
    return isinstance(value, str) and bool(value.strip())


# ``scheme://…@`` ahead of any path/query/fragment — the structural shape of
# embedded user information.
_URL_USERINFO_RE = re.compile(r"://[^/?#]*@")

# WHATWG URL parsing — every browser and Node runtime — is lenient about the
# ``//`` after a special scheme: it accepts any slash run (backslashes too),
# so a JS client reads ``https:user:pass@example.com/mcp`` as user
# information for example.com while RFC 3986, and urlsplit with it, see one
# opaque path. Such spellings are retried in their normalized form.
_WHATWG_SPECIAL_SCHEME_RE = re.compile(r"^(https?|wss?|ftp|file):", re.IGNORECASE)


def _url_has_userinfo(url: str) -> bool:
    """Whether a URL carries user information, even when malformed.

    urlsplit raises ValueError on some malformed URLs; the conservative
    fallback scans for the userinfo shape so an unparseable URL cannot
    smuggle embedded credentials past the check. Slashless special-scheme
    spellings are additionally retried the way a WHATWG client would
    normalize them.
    """

    def carries(candidate: str) -> bool:
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            return _URL_USERINFO_RE.search(candidate) is not None
        return parsed.username is not None or parsed.password is not None

    if carries(url):
        return True
    match = _WHATWG_SPECIAL_SCHEME_RE.match(url)
    if not match:
        return False
    rest = url[match.end() :]
    if rest.startswith("//"):
        # Already in authority form — the first parse was authoritative.
        return False
    # The lstrip lives outside the f-string: a backslash in an expression
    # is a SyntaxError on the 3.9–3.11 interpreters this package supports.
    stripped = rest.lstrip("/\\")
    return carries(f"{match.group(0)}//{stripped}".replace("\\", "/"))


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
        check_reserved: bool = True,
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
            # Sanitized once, used by every message below. A server name is
            # author-controlled text that lands in terminal output, JSON and
            # SARIF, so it gets the same treatment as any other echoed
            # manifest value: userinfo redacted, control characters and lone
            # surrogates replaced. Bound at the top of the loop rather than
            # per message so a diagnostic added later cannot forget it.
            shown = safe_display(server_name)
            if not isinstance(server_config, dict):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' configuration must be an object",
                        file_path=file_path,
                    )
                )
                continue

            if check_reserved and server_name in self.RESERVED_SERVER_NAMES:
                violations.append(
                    self.violation(
                        f"MCP server name '{shown}' is reserved "
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
                        f"MCP server '{shown}' has invalid type '{safe_display(server_type)}'. Must be one of: {', '.join(self.VALID_MCP_TYPES)}",
                        file_path=file_path,
                    )
                )
            else:
                required_field = self.REQUIRED_FIELDS_BY_TYPE[server_type]
                if required_field not in server_config:
                    violations.append(
                        self.violation(
                            f"MCP server '{shown}' with type '{safe_display(server_type)}' must have a '{required_field}' field",
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
                            f"MCP server '{shown}' '{required_field}' "
                            "must be a non-empty string",
                            file_path=file_path,
                        )
                    )

            if "args" in server_config and not isinstance(server_config["args"], list):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' 'args' must be an array",
                        file_path=file_path,
                    )
                )

            if "env" in server_config and not isinstance(server_config["env"], dict):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' 'env' must be an object",
                        file_path=file_path,
                    )
                )
            elif isinstance(server_config.get("env"), dict):
                violations.extend(
                    self._mapped_secret_violations(
                        server_config["env"],
                        server_name=shown,
                        file_path=file_path,
                        header=False,
                    )
                )

            if "cwd" in server_config and not isinstance(server_config["cwd"], str):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' 'cwd' must be a string",
                        file_path=file_path,
                    )
                )

            if "url" in server_config and not isinstance(server_config["url"], str):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' 'url' must be a string",
                        file_path=file_path,
                    )
                )
            elif isinstance(server_config.get("url"), str):
                if _url_has_userinfo(server_config["url"]):
                    violations.append(
                        self.violation(
                            f"MCP server '{shown}' 'url' must not contain user information",
                            file_path=file_path,
                        )
                    )

            if "headers" in server_config and not isinstance(server_config["headers"], dict):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' 'headers' must be an object",
                        file_path=file_path,
                    )
                )
            elif isinstance(server_config.get("headers"), dict):
                violations.extend(
                    self._mapped_secret_violations(
                        server_config["headers"],
                        server_name=shown,
                        file_path=file_path,
                        header=True,
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
                            self.violation(
                                f"MCP server '{shown}' '{timeout_field}' must be a number",
                                file_path=file_path,
                            )
                        )

            if "headersHelper" in server_config and not isinstance(
                server_config["headersHelper"], str
            ):
                violations.append(
                    self.violation(
                        f"MCP server '{shown}' 'headersHelper' must be a string",
                        file_path=file_path,
                    )
                )

            if "alwaysLoad" in server_config:
                val = server_config["alwaysLoad"]
                if not isinstance(val, bool):
                    violations.append(
                        self.violation(
                            f"MCP server '{shown}' 'alwaysLoad' must be a boolean",
                            file_path=file_path,
                        )
                    )

            if "oauth" in server_config:
                oauth = server_config["oauth"]
                if not isinstance(oauth, dict):
                    violations.append(
                        self.violation(
                            f"MCP server '{shown}' 'oauth' must be an object",
                            file_path=file_path,
                        )
                    )

        return violations

    def _placeholder_markers(self) -> Tuple[str, ...]:
        """The placeholder allowlist, extended by this rule's configuration."""
        extra = self.config.get("additional-placeholders", [])
        if not isinstance(extra, list):
            return DEFAULT_PLACEHOLDER_MARKERS
        return DEFAULT_PLACEHOLDER_MARKERS + tuple(str(m).lower() for m in extra if str(m))

    def _mapped_secret_violations(
        self,
        values: Dict[Any, Any],
        *,
        server_name: str,
        file_path: Path,
        header: bool,
    ) -> List[RuleViolation]:
        """Report structured credentials without copying their values."""
        violations = []
        for name, value in values.items():
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            description = mapped_secret_description(
                name,
                value,
                header=header,
                markers=self._placeholder_markers(),
            )
            if description is None:
                continue
            location = "HTTP header" if header else "environment variable"
            violations.append(
                self.violation(
                    f"MCP server '{server_name}' {location} "
                    f"'{safe_display(name)}' embeds {description}; use a placeholder "
                    "or environment substitution instead of a credential value",
                    file_path=file_path,
                )
            )
        return violations
