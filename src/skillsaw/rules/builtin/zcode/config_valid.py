"""
Rule: zcode-config-valid

Checks the ``hooks`` and ``mcp`` sections of a ZCode project
``.zcode/config.json``. ZCode validates the project file with one strict
schema, so a single bad hooks key rejects the whole file — every project
hook and every MCP server in it — while a bad MCP server drops only itself.
"""

from typing import Any, Dict, List

from skillsaw.blocks import ZCodeConfigHooksBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.zcode import CONFIG_FILENAME, HOOK_EVENTS, TOOL_DIR_NAME
from skillsaw.paths import contained_resolve, safe_exists, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import ZCODE_PROJECT_REPO_TYPES, is_positive_number, matcher_group_problems

#: Keys the project ``hooks`` object accepts; it is a strict object
#: (``adapters/src/config/schema.ts:271-289`` in ``zai-org/ZCode``).
_HOOKS_KEYS = frozenset({"enabled", "timeoutMs", "maxOutputBytes", "events"})

#: Per-transport keys of a project MCP server, each a strict object
#: (``adapters/src/config/schema.ts:46-112``).
_SERVER_BASE_KEYS = frozenset(
    {"type", "alwaysLoad", "isolation", "protocolVersion", "enabled", "timeoutMs"}
)
_SERVER_KEYS = {
    "stdio": _SERVER_BASE_KEYS | {"command", "args", "cwd", "env"},
    "http": _SERVER_BASE_KEYS | {"url", "headers", "oauth"},
    "sse": _SERVER_BASE_KEYS | {"url", "headers", "oauth"},
}
#: Keys ZCode rewrites or deletes before validating a server, so they are
#: never "unknown" (``adapters/src/config/schema.ts:360-412``).
_NORMALIZED_KEYS = frozenset(
    {"environment", "enable", "timeout", "startup_timeout_sec", "http_headers"}
)

#: The article each transport name takes in a message.
_ARTICLE = {"stdio": "a", "http": "an", "sse": "an"}

#: Enumerated base fields (``adapters/src/config/schema.ts:46-54``).
_ENUM_FIELDS = {
    "isolation": ("session", "workspace"),
    "protocolVersion": ("auto", "legacy", "2026-07-28"),
}
#: OAuth grant types and the fields each requires
#: (``adapters/src/config/schema.ts:56-75``).
_OAUTH_REQUIRED = {"client_credentials": ("clientId", "clientSecret"), "authorization_code": ()}
#: Each grant is its own strict object: only ``authorization_code`` takes a
#: ``redirectPath``.
_OAUTH_KEYS = {
    "client_credentials": frozenset({"type", "clientId", "clientSecret", "clientName", "scope"}),
    "authorization_code": frozenset(
        {"type", "clientId", "clientSecret", "clientName", "redirectPath", "scope"}
    ),
}


def _field_problem(server: Dict[str, Any]) -> str:
    """Type errors in the accepted fields beyond the connection itself."""
    for key in ("alwaysLoad", "enabled"):
        if key in server and not isinstance(server[key], bool):
            return f"'{key}' must be a boolean"
    for key, allowed in _ENUM_FIELDS.items():
        if key in server and server[key] not in allowed:
            return f"'{key}' must be one of {', '.join(allowed)}"
    if "timeoutMs" in server and not is_positive_number(server["timeoutMs"]):
        return "'timeoutMs' must be a positive number"
    if "cwd" in server and not (isinstance(server["cwd"], str) and server["cwd"]):
        return "'cwd' must be a non-empty string"
    if "oauth" in server:
        oauth = server["oauth"]
        if not isinstance(oauth, dict) or not isinstance(oauth.get("type"), str):
            return "'oauth' must be an object with a 'type'"
        required = _OAUTH_REQUIRED.get(oauth["type"])
        if required is None:
            return "'oauth.type' must be client_credentials or authorization_code"
        allowed = _OAUTH_KEYS[oauth["type"]]
        unknown = sorted(set(oauth) - allowed)
        if unknown:
            return f"unknown 'oauth' key(s): {', '.join(safe_display(k) for k in unknown)}"
        for key in sorted(allowed - {"type"}):
            value = oauth.get(key)
            # Every field but ``scope`` is ``z.string().min(1)``.
            if key in oauth and not (isinstance(value, str) and (value or key == "scope")):
                return f"'oauth.{key}' must be a non-empty string"
        for key in required:
            if not oauth.get(key):
                return f"'oauth.{key}' is required for {oauth['type']}"
    return ""


_WHOLE_FILE = "ZCode rejects the whole file, so none of its hooks or MCP servers load"


class ZCodeConfigValidRule(Rule):
    """Check the hooks and MCP sections of a ZCode project config.json"""

    since = "0.23.0"

    repo_types = ZCODE_PROJECT_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "zcode-config-valid"

    @property
    def description(self) -> str:
        return "ZCode .zcode/config.json hooks and MCP servers must match ZCode's schema"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        root = safe_resolve(context.root_path)
        for zcode_dir in context.agent_tool_dirs(TOOL_DIR_NAME):
            config = zcode_dir / CONFIG_FILENAME
            if root is not None and safe_exists(config) and contained_resolve(config, root) is None:
                # ZCode follows the link and runs what it configures; the
                # tree does not attach it, so say so instead of going quiet.
                violations.append(
                    self.violation(
                        "config.json is a symlink out of the repository: ZCode loads its "
                        "hooks and MCP servers, but skillsaw cannot lint them. Commit the "
                        "file itself",
                        config,
                    )
                )
        for block in context.lint_tree.find(ZCodeConfigHooksBlock):
            if block.parse_error:
                violations.append(
                    self.violation(
                        f"Invalid JSON: {block.parse_error}; ZCode ignores the whole file",
                        file_path=block.path,
                    )
                )
                continue
            data = block.raw_data
            if not isinstance(data, dict):
                violations.append(
                    self.violation(
                        "Project config must be a JSON object; ZCode ignores the whole file",
                        file_path=block.path,
                    )
                )
                continue
            for problem in self._hooks_problems(data.get("hooks", {})):
                violations.append(self.violation(f"{problem}; {_WHOLE_FILE}", file_path=block.path))
            if "mcp" in data:
                violations.extend(self._mcp_violations(block, data["mcp"]))
        return violations

    @staticmethod
    def _hooks_problems(hooks: Any) -> List[str]:
        if not isinstance(hooks, dict):
            return ["'hooks' must be an object"]
        problems: List[str] = []
        for key in sorted(set(hooks) - _HOOKS_KEYS):
            problems.append(
                f"Unknown key 'hooks.{safe_display(key)}' (allowed: {', '.join(sorted(_HOOKS_KEYS))}); "
                "hook events go under 'hooks.events'"
            )
        if "enabled" in hooks and not isinstance(hooks["enabled"], bool):
            problems.append("'hooks.enabled' must be a boolean")
        for key in ("timeoutMs", "maxOutputBytes"):
            if key in hooks and not is_positive_number(hooks[key]):
                problems.append(f"'hooks.{key}' must be a positive number")
        events = hooks.get("events", {})
        if not isinstance(events, dict):
            problems.append("'hooks.events' must be an object")
            return problems
        for event, groups in events.items():
            if event not in HOOK_EVENTS:
                problems.append(
                    f"Unknown event 'hooks.events.{safe_display(event)}' "
                    f"(ZCode's events: {', '.join(sorted(HOOK_EVENTS))})"
                )
                continue
            if not isinstance(groups, list):
                problems.append(
                    f"'hooks.events.{safe_display(event)}' must be an array of matcher groups"
                )
                continue
            for index, group in enumerate(groups):
                for problem in matcher_group_problems(group, project=True):
                    problems.append(f"hooks.events.{safe_display(event)}[{index}]: {problem}")
        return problems

    def _mcp_violations(self, block: ZCodeConfigHooksBlock, mcp: Any) -> List[RuleViolation]:
        if not isinstance(mcp, dict):
            return [self.violation(f"'mcp' must be an object; {_WHOLE_FILE}", file_path=block.path)]
        if "servers" not in mcp:
            return []
        servers = mcp["servers"]
        if not isinstance(servers, dict):
            return [
                self.violation(
                    "'mcp.servers' must be an object mapping names to servers; "
                    "ZCode ignores every MCP server in this file",
                    file_path=block.path,
                )
            ]
        violations = []
        for name, server in servers.items():
            problem = self._server_problem(server)
            if problem:
                violations.append(
                    self.violation(
                        f"MCP server {safe_display(name)!r}: {problem}; ZCode skips this server",
                        file_path=block.path,
                    )
                )
        return violations

    @staticmethod
    def _server_problem(server: Any) -> str:
        """The first reason ZCode's per-server schema rejects *server*, or ``""``."""
        if not isinstance(server, dict):
            return "must be an object"
        kind = server.get("type")
        if kind == "remote":
            kind = "http"
        elif not isinstance(kind, str):
            if isinstance(server.get("command"), str) and server["command"].strip():
                kind = "stdio"
            elif isinstance(server.get("url"), str) and server["url"].strip():
                kind = "http"
            else:
                return "has no 'type' and neither a 'command' nor a 'url' to infer one from"
        if kind not in _SERVER_KEYS:
            return f"'type' must be stdio, http or sse (got {safe_display(kind)!r})"
        keys = set(server)
        if "environment" in keys and "env" not in keys:
            keys.add("env")  # ZCode renames it before validating
        unknown = sorted(keys - _SERVER_KEYS[kind] - _NORMALIZED_KEYS)
        if unknown:
            return f"unknown key(s) for {_ARTICLE[kind]} {kind} server: {', '.join(safe_display(k) for k in unknown)}"
        field = "command" if kind == "stdio" else "url"
        if not isinstance(server.get(field), str) or not server[field]:
            return f"{_ARTICLE[kind]} {kind} server needs a non-empty '{field}'"
        # A legacy alias is read only when its canonical key is absent, and
        # ``http_headers`` only on a remote server; otherwise ZCode deletes it
        # unread (``adapters/src/config/schema.ts:360-412``).
        string_maps: Dict[str, Any] = {
            key: server[key] for key in ("env", "headers") if key in server
        }
        if "environment" in server and "env" not in server:
            string_maps["environment"] = server["environment"]
        if "http_headers" in server and "headers" not in server and kind != "stdio":
            string_maps["http_headers"] = server["http_headers"]
        for key, value in string_maps.items():
            if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
                return f"'{key}' must be an object of string values"
        if "args" in server and (
            not isinstance(server["args"], list)
            or not all(isinstance(a, str) for a in server["args"])
        ):
            return "'args' must be an array of strings"
        return _field_problem(server)
