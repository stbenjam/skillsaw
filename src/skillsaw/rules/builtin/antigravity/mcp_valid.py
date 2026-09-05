"""Rule: antigravity-mcp-valid."""

from __future__ import annotations

from typing import Any, FrozenSet, List, Optional, Tuple

from skillsaw.blocks.antigravity_mcp import field_occurrences
from skillsaw.blocks.json_config import AntigravityMcpBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import antigravity
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity

#: What a per-server defect costs, and the reason it is worth reporting at
#: all: ``agy`` drops the server and says nothing, so the tools it was
#: meant to provide are simply absent from the session.
_SERVER_DROPPED = "Antigravity drops the server silently and loads the rest of the file"


class AntigravityMcpValidRule(Rule):
    """Validate an Antigravity ``mcp_config.json``.

    Two failure scopes, both measured against ``agy`` 1.1.26:

    * A JSON syntax error, or a non-null root/wrapper that is not an object, is
      **startup-fatal** — ``agy`` exits 1 with one message naming the file,
      and no session starts. That is the ERROR half.
    * A per-server shape problem drops **that server only, silently**.
      There is no diagnostic and no middle ground. That is the WARNING
      half, and it is the half a repository cannot discover on its own.

    A missing connection field is deliberately not reported: ``serverUrl``
    wins over ``command`` when both are present, ``url`` with an optional
    ``type`` is a third accepted form, and a server carrying none of them
    loads without any ``agy`` complaint.
    """

    since = "0.20.0"
    # ``enabled: auto`` on the base default, gated on the two places these
    # files live: an Antigravity workspace and an Antigravity plugin.
    # Whatever gates this rule off — a forced ``--type``, a ``version:``
    # pin, an explicit ``enabled: false`` — ``mcp-valid-json`` keeps
    # scanning the file for a committed credential and a connection URL
    # carrying user information, and takes back neither the shape walk nor
    # the parse failure: the Claude-family reading would report this
    # dialect's correct file as invalid.
    repo_types = frozenset({RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN})

    config_schema = {
        "extra-auth-provider-types": {
            "type": "list",
            "default": [],
            "description": (
                "Additional 'authProviderType' values to accept, for providers "
                "newer than this skillsaw release"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "antigravity-mcp-valid"

    @property
    def description(self) -> str:
        return "mcp_config.json must parse and declare servers Antigravity can load"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _accepted_auth_providers(self) -> FrozenSet[str]:
        """The measured provider, plus any the project declares.

        A release that adds a second provider would otherwise turn a
        working file into a finding with no way out but disabling the rule.

        The declared type is not enforced when the config loads, so
        ``extra-auth-provider-types: 42`` arrives here as an int. Iterating
        it would raise ``TypeError`` and cost every finding in every MCP
        file over one bad config line.
        """
        extra = self.setting("extra-auth-provider-types") or []
        if not isinstance(extra, (list, tuple, set, frozenset)):
            return antigravity.MCP_AUTH_PROVIDER_TYPES
        return antigravity.MCP_AUTH_PROVIDER_TYPES | {
            value for value in extra if isinstance(value, str)
        }

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        accepted = self._accepted_auth_providers()
        for block in context.lint_tree.find(AntigravityMcpBlock):
            violations.extend(self._check_file(block, accepted))
        return violations

    def _check_file(
        self, block: AntigravityMcpBlock, accepted: FrozenSet[str]
    ) -> List[RuleViolation]:
        if block.has_utf8_bom():
            return [
                self.violation(
                    "mcp_config.json starts with a UTF-8 BOM; remove it so Antigravity can "
                    "parse the file (otherwise it exits 1 and no session starts)",
                    file_path=block.path,
                    fingerprint_discriminator="utf8-bom",
                )
            ]
        if block.parse_error:
            return [
                self.violation(
                    f"Invalid JSON: {safe_display(block.parse_error)}; Antigravity exits 1 "
                    "and no session starts",
                    file_path=block.path,
                    fingerprint_discriminator="parse-error",
                )
            ]
        data = block.raw_data
        if not isinstance(data, dict):
            return [
                self.violation(
                    "mcp_config.json must be a JSON object; Antigravity exits 1 and no "
                    "session starts",
                    file_path=block.path,
                    fingerprint_discriminator="root-not-object",
                )
            ]

        servers = data.get(block.servers_key)
        if servers is not None and not isinstance(servers, dict):
            return [
                self.violation(
                    "'mcpServers' must be a JSON object or null; Antigravity exits 1 "
                    "at startup and no session starts",
                    file_path=block.path,
                    fingerprint_discriminator="mcpservers-not-object",
                )
            ]
        if not isinstance(servers, dict):
            # A bare server map — the shape several other hosts accept — is
            # not an error here. ``agy`` reads no wrapper, finds no servers,
            # and starts anyway, so the file is inert rather than broken.
            return [
                self.violation(
                    f"no '{block.servers_key}' object, so Antigravity loads no server "
                    "from this file",
                    file_path=block.path,
                    severity=Severity.WARNING,
                    fingerprint_discriminator="no-mcpservers",
                )
            ]

        violations: List[RuleViolation] = []
        for name, server in servers.items():
            violations.extend(self._check_server(block, str(name), server, accepted))
        return violations

    def _inert(self, block: AntigravityMcpBlock, name: str, problem: str) -> RuleViolation:
        """A server that loads and can do nothing, which is not the same defect.

        ``agy mcp list`` shows it enabled with an empty command column: the
        session carries a server that will never start, so "dropped" would
        send the author looking for the wrong thing.
        """
        return self.violation(
            f"MCP server '{name}': {problem}; Antigravity loads the server and it starts nothing",
            file_path=block.path,
            severity=Severity.WARNING,
            fingerprint_discriminator=f"{name}:{problem}",
        )

    def _dropped(self, block: AntigravityMcpBlock, name: str, problem: str) -> RuleViolation:
        return self.violation(
            f"MCP server '{name}': {problem}; {_SERVER_DROPPED}",
            file_path=block.path,
            severity=Severity.WARNING,
            fingerprint_discriminator=f"{name}:{problem}",
        )

    def _check_server(
        self, block: AntigravityMcpBlock, name: str, server: Any, accepted: FrozenSet[str]
    ) -> List[RuleViolation]:
        shown = safe_display(name)
        if not isinstance(server, dict):
            return [self._dropped(block, shown, "a server must be a JSON object")]

        violations: List[RuleViolation] = []
        seen = set()
        for spelling, value in field_occurrences(server):
            key = antigravity.mcp_field_name(spelling)
            problem = self._field_problem(key, spelling, value, accepted)
            if problem is not None and (key, problem[0]) not in seen:
                seen.add((key, problem[0]))
                violations.append(self._dropped(block, shown, problem[1]))

        if (
            not violations
            and server.get("command") == ""
            and not server.get("serverUrl")
            and not server.get("url")
        ):
            violations.append(self._inert(block, shown, "'command' is empty"))
        return violations

    def _field_problem(
        self, key: str, spelling: str, value: Any, accepted: FrozenSet[str]
    ) -> Optional[Tuple[str, str]]:
        """Validate each occurrence before a later duplicate can erase its error."""
        if value is None:
            return None
        shown = safe_display(spelling)
        if key in ("env", "headers", "oauth"):
            if not isinstance(value, dict):
                return f"{key}-not-object", f"'{shown}' must be an object"
            if key == "oauth":
                for member, item in field_occurrences(value):
                    if (
                        antigravity.mcp_field_name(member, oauth=True)
                        in antigravity.MCP_CREDENTIAL_FIELDS
                        and item is not None
                        and not isinstance(item, str)
                    ):
                        return "oauth-value-type", (
                            f"'{shown}.{safe_display(member)}' must be a string or null"
                        )
            elif any(v is not None and not isinstance(v, str) for _, v in field_occurrences(value)):
                return f"{key}-value-type", f"every '{shown}' value must be a string"
        elif key in ("args", "disabledTools"):
            if key == "args" and not isinstance(value, list):
                return "args-not-array", f"'{shown}' must be an array"
            if not isinstance(value, list) or any(
                v is not None and not isinstance(v, str) for v in value
            ):
                if key == "args":
                    return "args-element-type", f"every '{shown}' element must be a string"
                return (
                    "disabled-tools-type",
                    f"'{shown}' must be an array of strings",
                )
        elif key in antigravity.MCP_STRING_FIELDS and not isinstance(value, str):
            return f"{key}-type", f"'{shown}' must be a string"
        elif key == "disabled" and not isinstance(value, bool):
            return "disabled-type", f"'{shown}' must be a boolean or null"
        elif key == "authProviderType" and (not isinstance(value, str) or value not in accepted):
            allowed = ", ".join(f"'{safe_display(v)}'" for v in sorted(accepted))
            return "auth-provider", f"'{shown}' must be {allowed}"
        return None
