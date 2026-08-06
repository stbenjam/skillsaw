"""Rule: agent-plugin-mcp-valid."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.agent_plugins import MCP_SCHEMA_ID, agent_plugin_schema_version
from skillsaw.lint_target import AgentPluginConfigNode
from skillsaw.paths import (
    contained_resolve,
    is_absolute_path,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.secret_detection import (
    DEFAULT_PLACEHOLDER_MARKERS,
    mapped_secret_description,
)

from ._helpers import (
    AGENT_PLUGIN_REPO_TYPES,
    MCP_SCHEMA,
    MCP_VALIDATOR,
    schema_error_summary,
    stable_key,
    strict_json,
)

_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_SERVER_SCHEMA_NAMES = {
    "stdio": "stdioServer",
    "streamable-http": "streamableHttpServer",
    "sse": "sseServer",
}
_SERVER_VALIDATORS = {
    server_type: MCP_VALIDATOR.evolve(schema=MCP_SCHEMA["$defs"][schema_name])
    for server_type, schema_name in _SERVER_SCHEMA_NAMES.items()
}


def _is_control_character(char: str) -> bool:
    """Whether *char* is a C0 control, DEL, or a C1 control (0x80-0x9F)."""
    point = ord(char)
    return point < 32 or 127 <= point <= 159


class AgentPluginMcpValidRule(Rule):
    """Validate Agent Plugins mcp.json with component/server isolation."""

    repo_types = AGENT_PLUGIN_REPO_TYPES
    since = "0.18.0"

    # Mirrors ``content-embedded-secrets``: a project that allowlisted its own
    # placeholder convention for prose must not be told its mcp.json embeds a
    # credential for the same value.
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

    @property
    def rule_id(self) -> str:
        return "agent-plugin-mcp-valid"

    @property
    def description(self) -> str:
        return "Agent Plugins mcp.json must conform to the 1.0.0 schema and semantics"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for node in context.lint_tree.find(AgentPluginConfigNode):
            violations.extend(self._check_mcp(node))
        return violations

    def _check_mcp(self, node: AgentPluginConfigNode) -> List[RuleViolation]:
        mcp_path = node.plugin_dir / "mcp.json"
        if not (safe_exists(mcp_path) or safe_is_symlink(mcp_path)):
            return []

        plugin_root = safe_resolve(node.plugin_dir)
        if plugin_root is None:
            return [
                self.violation(
                    "Plugin root cannot be resolved safely",
                    file_path=mcp_path,
                    fingerprint_discriminator="mcp:root-unresolved",
                )
            ]
        resolved_mcp = contained_resolve(mcp_path, plugin_root)
        if resolved_mcp is None:
            return [
                self.violation(
                    "mcp.json must resolve within the plugin root",
                    file_path=mcp_path,
                    fingerprint_discriminator="mcp:escape",
                )
            ]
        if not safe_is_file(resolved_mcp):
            return [
                self.violation(
                    "mcp.json must resolve to a regular file",
                    file_path=mcp_path,
                    fingerprint_discriminator="mcp:not-file",
                )
            ]

        data, error = strict_json(mcp_path)
        if error:
            return [
                self.violation(
                    f"Invalid JSON: {error}",
                    file_path=mcp_path,
                    fingerprint_discriminator="mcp:json",
                )
            ]
        if not isinstance(data, dict):
            return [
                self.violation(
                    "mcp.json must contain a JSON object",
                    file_path=mcp_path,
                    fingerprint_discriminator="mcp:not-object",
                )
            ]

        servers = data.get("mcpServers")
        top_view = dict(data)
        if isinstance(servers, dict):
            # Validate top-level shape separately so one malformed server does
            # not disable diagnostics for valid siblings.
            top_view["mcpServers"] = {}
        version_problem: Optional[str] = None
        declared_schema = top_view.get("$schema")
        if "$schema" in top_view and declared_schema != MCP_SCHEMA_ID:
            declared_version = agent_plugin_schema_version(declared_schema, "mcp")
            version_problem = (
                f"unsupported Agent Plugins MCP schema version "
                f"'{safe_display(declared_version)}'; this skillsaw release supports 1.0.0"
                if declared_version is not None
                else (
                    "'$schema' must be the canonical Agent Plugins 1.0.0 " "MCP schema identifier"
                )
            )
            # The friendly diagnostic replaces the schema's duplicate const
            # error without weakening any other top-level validation.
            top_view["$schema"] = MCP_SCHEMA_ID
        top_errors = list(MCP_VALIDATOR.iter_errors(top_view))

        resolved_manifest = contained_resolve(node.path, plugin_root)
        plugin_data, plugin_error = (
            strict_json(resolved_manifest)
            if resolved_manifest is not None and safe_is_file(resolved_manifest)
            else (None, "manifest is unavailable")
        )
        plugin_version = (
            agent_plugin_schema_version(plugin_data.get("$schema"), "plugin")
            if plugin_error is None and isinstance(plugin_data, dict)
            else None
        )
        mcp_version = agent_plugin_schema_version(data.get("$schema"), "mcp")
        mismatch = (
            plugin_version is not None and mcp_version is not None and plugin_version != mcp_version
        )
        if top_errors or mismatch or version_problem:
            reasons: List[str] = []
            if version_problem:
                reasons.append(version_problem)
            if top_errors:
                reasons.append(schema_error_summary(top_errors))
            if mismatch:
                reasons.append(
                    f"schema version {safe_display(mcp_version)} does not match "
                    f"plugin.json version {safe_display(plugin_version)}"
                )
            return [
                self.violation(
                    f"mcp.json top level is invalid: {'; '.join(reasons)}",
                    file_path=mcp_path,
                    fingerprint_discriminator="mcp:top-level",
                )
            ]

        # The schema guarantees this after the top-level validation above.
        assert isinstance(servers, dict)
        violations: List[RuleViolation] = []
        for server_name, server in servers.items():
            server_type = server.get("type") if isinstance(server, dict) else None
            validator = (
                _SERVER_VALIDATORS.get(server_type) if isinstance(server_type, str) else None
            )
            if validator is None:
                schema_errors = []
                schema_problem = (
                    "configuration must be an object with a recognized "
                    "'type' (stdio, streamable-http, or sse)"
                )
            else:
                schema_errors = list(validator.iter_errors(server))
                schema_problem = schema_error_summary(schema_errors, limit=2)
            if validator is None or schema_errors:
                violations.append(
                    self.violation(
                        f"MCP server '{safe_display(server_name)}' is invalid: "
                        f"{schema_problem}",
                        file_path=mcp_path,
                        fingerprint_discriminator=(f"mcp:server:{stable_key(server_name)}:schema"),
                    )
                )
                continue
            assert isinstance(server, dict)
            problem = self._semantic_problem(server, node.plugin_dir, plugin_root)
            if problem:
                violations.append(
                    self.violation(
                        f"MCP server '{safe_display(server_name)}' is invalid: {problem}",
                        file_path=mcp_path,
                        fingerprint_discriminator=(
                            f"mcp:server:{stable_key(server_name)}:semantics"
                        ),
                    )
                )
        return violations

    def _semantic_problem(
        self, server: Dict[str, Any], plugin_dir: Path, plugin_root: Path
    ) -> Optional[str]:
        server_type = server["type"]
        if server_type == "stdio":
            command_problem = self._command_problem(server["command"], plugin_dir, plugin_root)
            if command_problem:
                return command_problem
            env_problem = self._mapped_secret_problem(server.get("env", {}), header=False)
            if env_problem:
                return env_problem
            cwd = server.get("cwd")
            if cwd is not None:
                return self._cwd_problem(cwd, plugin_dir, plugin_root)
            return None
        return self._remote_problem(server["url"], server.get("headers", {}))

    @staticmethod
    def _command_problem(command: str, plugin_dir: Path, plugin_root: Path) -> Optional[str]:
        # A control character in an executable token is either a mis-encoded
        # value or an attempt to smuggle one token past a naive reader; it is
        # never part of a real program name, in either accepted form.
        if any(_is_control_character(char) for char in command):
            return "'command' must not contain control characters"
        if command.startswith("./"):
            suffix = command[2:]
            resolved = contained_resolve(plugin_dir / command, plugin_root)
            if (
                is_absolute_path(suffix)
                or AgentPluginMcpValidRule._relative_path_escapes(suffix)
                or resolved is None
            ):
                return "'command' resolves outside the plugin root"
            # './', './.' and './bin/..' all name the plugin root itself, which
            # is a directory, not the executable the field must identify. The
            # lexical check catches those without requiring the binary to
            # exist (it may only appear post-install); the filesystem check
            # rejects a path that already exists as a directory.
            if not AgentPluginMcpValidRule._normalized_parts(suffix) or safe_is_dir(resolved):
                return "'command' must name an executable file, not a directory"
            return None
        if is_absolute_path(command) or "/" in command or "\\" in command:
            return "'command' must be a bare executable name or begin with './'"
        # A bare name cannot be a path, so whitespace means the value packs
        # arguments into the executable token ("node --eval …", "sh -c").
        # Only whitespace is rejected: shell metacharacters are legal in file
        # names, and rejecting them would fail valid single-token commands.
        if any(char.isspace() for char in command):
            return (
                "'command' must be a single executable token; "
                "arguments must be supplied via 'args'"
            )
        return None

    @staticmethod
    def _cwd_problem(cwd: str, plugin_dir: Path, plugin_root: Path) -> Optional[str]:
        if cwd.startswith("./"):
            suffix = cwd[2:]
            if (
                is_absolute_path(suffix)
                or AgentPluginMcpValidRule._relative_path_escapes(suffix)
                or contained_resolve(plugin_dir / cwd, plugin_root) is None
            ):
                return "'cwd' resolves outside the plugin root"
            return None

        for placeholder in ("${PLUGIN_ROOT}", "${PLUGIN_DATA}"):
            if cwd != placeholder and not cwd.startswith(f"{placeholder}/"):
                continue
            suffix = cwd[len(placeholder) :]
            remainder = suffix[1:] if suffix.startswith("/") else suffix
            if is_absolute_path(remainder) or AgentPluginMcpValidRule._relative_path_escapes(
                remainder
            ):
                return f"'cwd' escapes {placeholder}"
            if placeholder == "${PLUGIN_ROOT}":
                if contained_resolve(plugin_dir / remainder, plugin_root) is None:
                    return "'cwd' resolves outside the plugin root"
            return None
        return "'cwd' must begin with './', '${PLUGIN_ROOT}', or '${PLUGIN_DATA}'"

    @staticmethod
    def _normalized_parts(value: str) -> Optional[List[str]]:
        """The path components *value* names, or ``None`` when it escapes.

        Safe internal normalization such as ``cache/../cache`` is valid under
        the spec's post-resolution containment rule. Treat both separators as
        portable input so a value checked on POSIX cannot escape on Windows.
        An empty list means the value names its own logical root.
        """
        parts: List[str] = []
        for part in value.replace("\\", "/").split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if not parts:
                    return None
                parts.pop()
            else:
                parts.append(part)
        return parts

    @staticmethod
    def _relative_path_escapes(value: str) -> bool:
        """Whether a relative path crosses above its logical root."""
        return AgentPluginMcpValidRule._normalized_parts(value) is None

    def _placeholder_markers(self) -> Tuple[str, ...]:
        """The placeholder allowlist, extended by this rule's configuration."""
        extra = self.config.get("additional-placeholders", [])
        if not isinstance(extra, list):
            return DEFAULT_PLACEHOLDER_MARKERS
        return DEFAULT_PLACEHOLDER_MARKERS + tuple(str(m).lower() for m in extra if str(m))

    def _remote_problem(self, url: str, headers: Dict[str, str]) -> Optional[str]:
        if any(ord(char) <= 32 or ord(char) == 127 for char in url):
            return "'url' must be an absolute HTTP or HTTPS URL"
        try:
            parsed = urlsplit(url)
            hostname = parsed.hostname
            # Force invalid/overflowing ports to raise now.
            parsed.port
        except ValueError:
            return "'url' must be an absolute HTTP or HTTPS URL"
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or hostname is None:
            return "'url' must be an absolute HTTP or HTTPS URL"
        if parsed.username is not None or parsed.password is not None:
            return "'url' must not contain user information"
        if "#" in url:
            return "'url' must not contain a fragment"
        if parsed.scheme == "http" and not AgentPluginMcpValidRule._is_loopback(hostname):
            return "non-loopback MCP endpoints must use HTTPS"

        seen = set()
        for name, value in headers.items():
            folded = name.casefold()
            if folded in seen:
                return f"duplicate case-insensitive header name '{safe_display(name)}'"
            seen.add(folded)
            if not _HEADER_NAME.fullmatch(name):
                return f"invalid HTTP header name '{safe_display(name)}'"
            # HTAB is the one control character RFC 9110 allows inside a field
            # value; everything else in C0, DEL, and C1 (NEL, CSI, …) is
            # rejected, since a header carrying one is either mis-encoded or a
            # header-injection attempt.
            if any(char != "\t" and _is_control_character(char) for char in value):
                return f"HTTP header '{safe_display(name)}' contains a control character"
        secret_problem = self._mapped_secret_problem(headers, header=True)
        if secret_problem:
            return secret_problem
        return None

    def _mapped_secret_problem(self, values: Dict[str, str], *, header: bool) -> Optional[str]:
        """Report a credential in an env/header map without exposing its value."""
        markers = self._placeholder_markers()
        for name, value in values.items():
            description = mapped_secret_description(name, value, header=header, markers=markers)
            if description is None:
                continue
            location = "HTTP header" if header else "environment variable"
            mapping = "headers" if header else "env"
            return (
                f"{location} '{safe_display(name)}' embeds {description}; "
                f"Agent Plugins must not embed credentials or secrets in '{mapping}'"
            )
        return None

    @staticmethod
    def _is_loopback(hostname: str) -> bool:
        if hostname.casefold() == "localhost":
            return True
        try:
            return ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            return False
