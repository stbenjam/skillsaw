"""Rule: antigravity-mcp-valid."""

from __future__ import annotations

from typing import Any, FrozenSet, List

from skillsaw.blocks import json_token
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

    Two failure scopes, both measured against ``agy`` 1.1.25:

    * A JSON syntax error or a root that is not an object is
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
        if block.parse_error:
            return [
                self.violation(
                    f"Invalid JSON: {safe_display(block.parse_error)}; Antigravity exits 1 "
                    "and no session starts",
                    file_path=block.path,
                    fingerprint_discriminator="parse-error",
                )
            ]
        found = block.first_non_finite()
        if found is not None:
            path, value = found
            return [
                self.violation(
                    f"'{json_token(value)}' at {safe_display(path)} is not valid JSON; "
                    "Antigravity exits 1 and no session starts",
                    file_path=block.path,
                    fingerprint_discriminator="non-finite",
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
        env = server.get("env")
        if env is not None:
            if not isinstance(env, dict):
                violations.append(self._dropped(block, shown, "'env' must be an object"))
            elif not all(isinstance(value, str) for value in env.values()):
                violations.append(self._dropped(block, shown, "every 'env' value must be a string"))

        args = server.get("args")
        if args is not None:
            if not isinstance(args, list):
                violations.append(self._dropped(block, shown, "'args' must be an array"))
            elif not all(isinstance(arg, str) for arg in args):
                violations.append(
                    self._dropped(block, shown, "every 'args' element must be a string")
                )

        # ``is not None`` rather than ``in``: Go decodes ``null`` as the
        # zero value, so a null field reads as absent and the server loads.
        if server.get("serverUrl") is not None and not isinstance(server["serverUrl"], str):
            violations.append(self._dropped(block, shown, "'serverUrl' must be a string"))

        disabled_tools = server.get("disabledTools")
        if disabled_tools is not None and not (
            isinstance(disabled_tools, list)
            and all(isinstance(tool, str) for tool in disabled_tools)
        ):
            violations.append(
                self._dropped(block, shown, "'disabledTools' must be an array of strings")
            )

        auth = server.get("authProviderType")
        # ``isinstance`` first: an array or an object is unhashable, and
        # testing set membership on one raises rather than reporting the
        # server ``agy`` drops for exactly that reason.
        if auth is not None and (not isinstance(auth, str) or auth not in accepted):
            rendered = ", ".join(f"'{safe_display(value)}'" for value in sorted(accepted))
            violations.append(
                self._dropped(
                    block,
                    shown,
                    f"'authProviderType' must be {rendered}",
                )
            )
        return violations
