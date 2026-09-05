"""
Rule: grok-config-valid

Validates syntax and configuration in Grok Build project ``.grok/config.toml``.
Verifies TOML syntax, MCP server entries under ``[mcp_servers]``, and tool
permissions under ``[permission]``.
"""

from typing import Any, Dict, List

from skillsaw.blocks import GrokConfigBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats import grok
from skillsaw.formats.grok_mcp import decode_mcp_server
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import sample

#: The TOML type each Python type was read as, in the spelling TOML uses.
#: Hoisted, because ``_type_name`` is called once per defective field.
_TOML_TYPE_NAMES = {
    bool: "boolean",
    dict: "table",
    float: "float",
    int: "integer",
    list: "array",
    str: "string",
}


class GrokConfigValidRule(Rule):
    """Validate a Grok Build project config.toml"""

    since = "0.20.0"

    # ``enabled: auto`` on the base default, gated on the one place this
    # file lives: a checkout carrying a ``.grok/`` project layer.
    repo_types = frozenset({RepositoryType.GROK_PROJECT})

    @property
    def rule_id(self) -> str:
        return "grok-config-valid"

    @property
    def description(self) -> str:
        return ".grok/config.toml must parse, and its servers and permissions must load"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for block in context.lint_tree.find(GrokConfigBlock):
            if block.parse_error:
                violations.append(
                    self.violation(
                        # Bounded: a TOML parser interpolates the offending
                        # key into its message, so an adversarial file would
                        # otherwise write its own content into the report.
                        f"Invalid TOML: {safe_display(block.parse_error)}",
                        file_path=block.path,
                    )
                )
                continue

            data = block.raw_data
            if data is None:
                # A non-table root, which TOML has no syntax for: the reader
                # returns a table or an error, and the branch above owns
                # every failure this file can have.
                continue

            violations.extend(self._check_servers(block, data))
            violations.extend(self._check_permission(block, data))

        return violations

    # -- ``[mcp_servers]`` ------------------------------------------

    def _check_servers(self, block: GrokConfigBlock, data: Dict[str, Any]) -> List[RuleViolation]:
        """The servers table, and each server Grok reads out of it."""
        key = block.servers_key
        if key not in data:
            return []
        if not isinstance(data[key], dict):
            return [
                self._warn(
                    block,
                    f"'{key}' must be a table of servers, got {_type_name(data[key])}",
                )
            ]

        violations: List[RuleViolation] = []
        for name, config in block.server_entries():
            where = f"[{key}.{safe_display(name)}]"
            if not isinstance(config, dict):
                violations.append(self._warn(block, f"{where} must be a table"))
                continue
            problems = decode_mcp_server(config)[1]
            if problems:
                # One finding per server: the defect is the server Grok
                # drops, and the problems are the reasons it drops it.
                violations.append(
                    self._warn(
                        block,
                        f"{where} {sample(problems)}",
                    )
                )
        return violations

    # -- ``[permission]`` -------------------------------------------

    def _check_permission(
        self, block: GrokConfigBlock, data: Dict[str, Any]
    ) -> List[RuleViolation]:
        """The table Grok reports nothing about, at any scope.

        The two array keys fail at different scopes, measured: a non-string
        in ``allow``/``deny``/``ask`` costs that entry, while a non-table in
        ``rules`` costs every rule in the array. The findings say which, so
        an author knows whether the rest of the key survived.

        A non-table ``permission`` is deliberately not reported: what it
        costs was never measured, and a rule may not invent the verdict.
        """
        table = data.get(grok.PERMISSION_TABLE)
        if not isinstance(table, dict):
            return []

        violations: List[RuleViolation] = []
        # Document order, so a file with two defects reads top to bottom. No
        # ``str()``: a TOML key is a string by grammar, unlike a YAML one.
        lists = [key for key in table if key in grok.PERMISSION_LIST_KEYS]
        for key in lists:
            value = table[key]
            if not isinstance(value, list):
                violations.append(
                    self._warn(
                        block,
                        f"[{grok.PERMISSION_TABLE}] '{key}' must be an array of rule "
                        f"strings, got {_type_name(value)}",
                    )
                )
                continue
            # Measured: a non-string entry costs that entry alone. The
            # string siblings beside it still load, and the key keeps its
            # place in ``permissions.sources``.
            dropped = _bad_entries(value, str)
            if dropped:
                violations.append(
                    self._warn(
                        block,
                        f"[{grok.PERMISSION_TABLE}] '{key}' entries must be rule "
                        f"strings; Grok drops {sample(dropped)}",
                    )
                )

        rules_key = grok.PERMISSION_RULES_KEY
        if rules_key not in table:
            return violations
        if lists:
            # Measured: every verbose rule is discarded whenever any of the
            # three list keys is present, in any order. Its type no longer
            # matters, so this is the file's one finding about it.
            violations.append(
                self._warn(
                    block,
                    f"[{grok.PERMISSION_TABLE}] '{rules_key}' is discarded because "
                    f"{_and_list(lists)} also set",
                )
            )
        elif not isinstance(table[rules_key], list):
            violations.append(
                self._warn(
                    block,
                    f"[{grok.PERMISSION_TABLE}] '{rules_key}' must be an array of tables, "
                    f"got {_type_name(table[rules_key])}",
                )
            )
        else:
            # Measured, and the opposite of the compact keys above: one
            # non-table entry costs the whole array. Two valid rules beside
            # a bare integer loaded nothing, silently.
            bad = _bad_entries(table[rules_key], dict)
            if bad:
                violations.append(
                    self._warn(
                        block,
                        f"[{grok.PERMISSION_TABLE}] '{rules_key}' entries must be tables; "
                        f"Grok discards the whole array over {sample(bad)}",
                    )
                )
        return violations

    def _warn(self, block: GrokConfigBlock, message: str) -> RuleViolation:
        """Report a warning-level violation scoped to an entry or field."""
        return self.violation(
            message, file_path=block.path, severity=self.scope_severity(Severity.WARNING)
        )


def _type_name(value: Any) -> str:
    """The TOML type *value* was read as, in the spelling TOML uses."""
    return _TOML_TYPE_NAMES.get(type(value), type(value).__name__)


def _bad_entries(values: List[Any], expected: type) -> List[str]:
    """Where *values* holds something other than *expected*, labelled.

    Positions count from one: a TOML array carries no index the author can
    read off the file, so the label has to be the one a reader would count.
    """
    return [
        f"entry {position} ({_type_name(value)})"
        for position, value in enumerate(values, 1)
        if not isinstance(value, expected)
    ]


def _and_list(names: List[str]) -> str:
    """*names* quoted and joined, with the verb the count needs."""
    quoted = [f"'{name}'" for name in names]
    if len(quoted) == 1:
        return f"{quoted[0]} is"
    return f"{', '.join(quoted[:-1])} and {quoted[-1]} are"
