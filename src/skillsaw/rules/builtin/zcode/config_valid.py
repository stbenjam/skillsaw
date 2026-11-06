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
from skillsaw.formats.zcode import HOOK_EVENTS
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import ZCODE_PROJECT_REPO_TYPES, matcher_group_problems

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

_WHOLE_FILE = "ZCode rejects the whole file, so none of its hooks or MCP servers load"


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


class ZCodeConfigValidRule(Rule):
    """Check the hooks and MCP sections of a ZCode project config.json"""

    since = "0.22.0"

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
            violations.extend(self._mcp_violations(block, data.get("mcp")))
        return violations

    @staticmethod
    def _hooks_problems(hooks: Any) -> List[str]:
        if not isinstance(hooks, dict):
            return ["'hooks' must be an object"]
        problems: List[str] = []
        for key in sorted(set(hooks) - _HOOKS_KEYS):
            problems.append(
                f"Unknown key 'hooks.{key}' (allowed: {', '.join(sorted(_HOOKS_KEYS))}); "
                "hook events go under 'hooks.events'"
            )
        if "enabled" in hooks and not isinstance(hooks["enabled"], bool):
            problems.append("'hooks.enabled' must be a boolean")
        for key in ("timeoutMs", "maxOutputBytes"):
            if key in hooks and not _positive(hooks[key]):
                problems.append(f"'hooks.{key}' must be a positive number")
        events = hooks.get("events", {})
        if not isinstance(events, dict):
            problems.append("'hooks.events' must be an object")
            return problems
        for event, groups in events.items():
            if event not in HOOK_EVENTS:
                problems.append(
                    f"Unknown event 'hooks.events.{event}' "
                    f"(ZCode's events: {', '.join(sorted(HOOK_EVENTS))})"
                )
                continue
            if not isinstance(groups, list):
                problems.append(f"'hooks.events.{event}' must be an array of matcher groups")
                continue
            for index, group in enumerate(groups):
                for problem in matcher_group_problems(group, project=True):
                    problems.append(f"hooks.events.{event}[{index}]: {problem}")
        return problems

    def _mcp_violations(self, block: ZCodeConfigHooksBlock, mcp: Any) -> List[RuleViolation]:
        if mcp is None:
            return []
        if not isinstance(mcp, dict):
            return [self.violation(f"'mcp' must be an object; {_WHOLE_FILE}", file_path=block.path)]
        servers = mcp.get("servers")
        if servers is None:
            return []
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
                        f"MCP server '{name}': {problem}; ZCode skips this server",
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
            return f"'type' must be stdio, http or sse (got {kind!r})"
        unknown = sorted(set(server) - _SERVER_KEYS[kind] - _NORMALIZED_KEYS)
        if unknown:
            return f"unknown key(s) for {_ARTICLE[kind]} {kind} server: {', '.join(unknown)}"
        field = "command" if kind == "stdio" else "url"
        if not isinstance(server.get(field), str) or not server[field]:
            return f"{_ARTICLE[kind]} {kind} server needs a non-empty '{field}'"
        string_maps: Dict[str, Any] = {
            key: server[key]
            for key in ("env", "environment", "headers", "http_headers")
            if key in server
        }
        for key, value in string_maps.items():
            if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
                return f"'{key}' must be an object of string values"
        if "args" in server and (
            not isinstance(server["args"], list)
            or not all(isinstance(a, str) for a in server["args"])
        ):
            return "'args' must be an array of strings"
        return ""
