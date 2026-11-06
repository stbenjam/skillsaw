"""Pi 1.5.0 MCP configuration types, transport selection, and project overrides."""

import re
from urllib.parse import urlsplit

from skillsaw.blocks.pi import PiMcpBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats.pi import (
    JS_TRIM_CHARS,
    MCP_CLIENT_REGISTRATIONS,
    MCP_DEFINITION_KEYS,
    MCP_EXPOSURES,
    MCP_HTTP_TYPES,
    MCP_OAUTH_STRING_FIELDS,
    MCP_OVERRIDE_KEYS,
)
from skillsaw.rule import Rule, Severity

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_SIMPLE_AUTHORITY = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9-]*\.)*[A-Za-z][A-Za-z0-9-]*(?::[0-9]{1,5})?\Z"
)


def _namespace_certain(server):
    """Reserve names only when the unchecked URI contract cannot reject them.

    An invalid predecessor is skipped by Pi and cannot conflict with a later
    server. Restrict HTTP admission to an ordinary ASCII DNS URL with no
    callback or authorization metadata URI; all other WHATWG cases remain
    with the native validator.
    """
    if not isinstance(server.get("url"), str) or server.get("type") == "stdio":
        return True
    url = server["url"]
    if (
        not url.isascii()
        or any(ord(char) <= 32 or ord(char) == 127 or char == "\\" for char in url)
        or any(
            field in server.get("oauth", {}) for field in ("callbackUrl", "authServerMetadataUrl")
        )
    ):
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme in {"http", "https"}
            and bool(_SIMPLE_AUTHORITY.fullmatch(parsed.netloc))
            and not any(
                label.lower().startswith("xn--") for label in (parsed.hostname or "").split(".")
            )
            and (parsed.port is None or parsed.port <= 65535)
        )
    except ValueError:
        return False


def _is_override(server):
    """A project entry with no command, url, or type overrides a global server."""
    return isinstance(server, dict) and not any(key in server for key in MCP_DEFINITION_KEYS)


def _strings(value):
    return isinstance(value, dict) and all(isinstance(v, str) for v in value.values())


def _problem(server):
    """Return one actionable reason Pi refuses this server's field types.

    Follow the HTTP-before-stdio choice, including ignored fields in the
    unselected transport. URI semantics remain with Pi's WHATWG parser.
    """
    if not isinstance(server, dict):
        return "expected a server object"
    override = _is_override(server)
    if override and any(key not in MCP_OVERRIDE_KEYS for key in server):
        return (
            f"an override can only set {', '.join(MCP_OVERRIDE_KEYS)}; "
            "add command or url to define a project server"
        )
    exposure = server.get("exposure")
    if "exposure" in server and (not isinstance(exposure, str) or exposure not in MCP_EXPOSURES):
        return "exposure must be codemode, deferred, direct, hidden, or codemode-deferred"
    if "toolExposure" in server:
        values = server["toolExposure"]
        if not isinstance(values, dict) or any(
            not isinstance(v, str) or v not in MCP_EXPOSURES for v in values.values()
        ):
            return "toolExposure must map tool names to supported exposure values"
    if "enabled" in server and not isinstance(server["enabled"], bool):
        return "enabled must be a boolean"
    if override:
        # Whether a global server of this name exists is outside the project.
        return None
    if "description" in server and not isinstance(server["description"], str):
        return "description must be a string"
    if "timeout" in server:
        value = server["timeout"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
            return "timeout must be a positive number of seconds"
    kind = server.get("type")
    if kind == "sse":
        return "legacy SSE is unsupported; use a streamable HTTP URL"
    if isinstance(server.get("url"), str) and (
        "type" not in server or isinstance(kind, str) and kind in MCP_HTTP_TYPES
    ):
        if "headers" in server and not _strings(server["headers"]):
            return "headers must map names to strings"
        if "oauth" in server:
            oauth = server["oauth"]
            if not isinstance(oauth, dict):
                return "oauth must be an object"
            for field in MCP_OAUTH_STRING_FIELDS:
                if field in oauth and not isinstance(oauth[field], str):
                    return f"oauth.{field} must be a string"
            if "clientName" in oauth and not oauth["clientName"].strip(JS_TRIM_CHARS):
                return "oauth.clientName must be nonempty"
            if "callbackPort" in oauth:
                port = oauth["callbackPort"]
                if (
                    isinstance(port, bool)
                    or not isinstance(port, (int, float))
                    or not 1 <= port <= 65535
                    or int(port) != port
                ):
                    return "oauth.callbackPort must be an integer from 1 to 65535"
            if "clientRegistration" in oauth:
                registration = oauth["clientRegistration"]
                if (
                    not isinstance(registration, str)
                    or registration not in MCP_CLIENT_REGISTRATIONS
                ):
                    return 'oauth.clientRegistration must be "auto", "dcr", or "cimd"'
                if registration == "cimd" and ("clientId" in oauth or "clientName" in oauth):
                    return (
                        'oauth.clientRegistration "cimd" cannot be combined with '
                        "oauth.clientId or oauth.clientName"
                    )
        if "auth" in server:
            return "auth is allowed only in the global mcp.json; use project OAuth or headers"
        return None
    if isinstance(server.get("command"), str) and ("type" not in server or kind == "stdio"):
        if "args" in server:
            args = server["args"]
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                return "args must be an array of strings"
        if "env" in server and not _strings(server["env"]):
            return "env must map names to strings"
        if "cwd" in server and not isinstance(server["cwd"], str):
            return "cwd must be a string"
        # The project loader tests property presence, not the selected
        # transport. JavaScript objects/arrays, including empty ones, are
        # truthy; Python's truthiness would admit an entry Pi refuses.
        auth = server.get("auth")
        if "url" in server and auth is not None and auth is not False and auth != 0 and auth != "":
            return "auth is allowed only in the global mcp.json; remove the project auth field"
        return None
    return "declare command with type stdio, or url with type http or streamable-http"


class PiMcpValidRule(Rule):
    """Validate the released Pi project MCP field contract."""

    since = "0.21.0"
    default_enabled = False
    repo_types = frozenset({RepositoryType.PI})

    @property
    def rule_id(self):
        return "pi-mcp-valid"

    @property
    def description(self):
        return "Pi MCP servers must use supported field types and transports"

    def default_severity(self):
        return Severity.WARNING

    def check(self, context: RepositoryContext):
        violations = []
        for block in context.lint_tree.find(PiMcpBlock):
            if block.parse_error:
                # The always-on shared MCP rule owns syntax errors.
                continue
            data = block.raw_data
            if not isinstance(data, dict) or (
                "mcpServers" in data and not isinstance(data["mcpServers"], dict)
            ):
                violations.append(
                    self.violation(
                        "Pi MCP configuration must be an object with an optional mcpServers object",
                        block=block,
                    )
                )
                continue
            if "autoEnableCodemode" in data and not isinstance(data["autoEnableCodemode"], bool):
                violations.append(
                    self.violation(
                        "autoEnableCodemode must be a boolean; Pi ignores this setting", block=block
                    )
                )
            entries = list(block.server_entries())
            # A valid override keeps the global server of that exact name, which
            # Pi loads before any project server, so its namespace is taken
            # wherever the override sits in the file. Global names cannot clash
            # with one another, so of two overrides in one namespace only the
            # first can refer to a surviving global server.
            seen = {}
            for name, server in entries:
                if (
                    _NAME.fullmatch(name) is not None
                    and _is_override(server)
                    and _problem(server) is None
                ):
                    seen.setdefault(name.replace("-", "_"), name)
            for name, server in entries:
                problem = (
                    "use only letters, digits, underscores, and hyphens in the server name"
                    if _NAME.fullmatch(name) is None
                    else _problem(server)
                )
                namespace = name.replace("-", "_")
                override = _is_override(server)
                certain = problem is None and (override or _namespace_certain(server))
                if certain and seen.get(namespace, name) != name:
                    problem = (
                        f"name conflicts with '{safe_display(seen[namespace])}'; "
                        "Pi treats hyphens and underscores as the same namespace"
                    )
                if problem is None and certain:
                    seen[namespace] = name
                elif problem is not None:
                    violations.append(
                        self.violation(
                            f"Pi skips MCP server '{safe_display(name)}': {problem}", block=block
                        )
                    )
        return violations
