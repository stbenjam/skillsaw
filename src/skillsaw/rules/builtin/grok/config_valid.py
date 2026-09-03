"""
Rule: grok-config-valid

The shape of a Grok Build project ``.grok/config.toml``, at the severity
each defect's blast radius earns. The vocabulary — the honoured tables, the
server fields, the transport derivation, the permission keys — lives in
``skillsaw.formats.grok``; this rule reads it and never restates it.

A parse error is the whole file: Grok loads nothing from it, including the
tables above the error, and exits 0 with an empty stderr. Everything below
that costs one server or one permission key, so it is a warning whatever
the rule's configured severity — the siblings and ``[permission]`` beside
it still load.

Grok is not silent everywhere here. A bad server shape raises
``mcpConfigProblems``, so those findings restate Grok's own verdict at lint
time; a bad ``[permission]`` shape raises nothing at all, which is where
the rule adds signal.

Only :class:`GrokConfigBlock` is iterated, a node type that exists only
where Grok's project layer does, so the rule declares no
``provenance_scope``: ``.grok/`` is a tool directory no other ecosystem
claims.
"""

from typing import Any, Dict, List, Optional

from skillsaw.blocks import GrokConfigBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats import grok
from skillsaw.rule import Rule, RuleViolation, Severity

#: Server fields whose TOML type Grok's deserializer pins. Read in this
#: order so a server carrying two defects names them the way the file does.
_TYPED_SERVER_FIELDS = ("command", "url", "args", "env", "headers")


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
        # The rule's own severity covers the whole-file defect only: a
        # malformed file loads nothing at all, and the sole signal Grok
        # gives is a ``note: "parse error"`` inside ``grok inspect``.
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for block in context.lint_tree.find(GrokConfigBlock):
            if block.parse_error:
                violations.append(
                    self.violation(
                        f"Invalid TOML: {block.parse_error}",
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
            where = f"[{key}.{safe_display(str(name))}]"
            if not isinstance(config, dict):
                violations.append(self._warn(block, f"{where} must be a table"))
                continue
            problems = _server_problems(config)
            if problems:
                # One finding per server: the defect is the server Grok
                # drops, and the problems are the reasons it drops it.
                violations.append(
                    self._warn(
                        block,
                        f"{where} {', '.join(problems)}",
                    )
                )
        return violations

    # -- ``[permission]`` -------------------------------------------

    def _check_permission(
        self, block: GrokConfigBlock, data: Dict[str, Any]
    ) -> List[RuleViolation]:
        """The table Grok reports nothing about, at any scope.

        A non-table ``permission`` is deliberately not reported: what it
        costs was never measured, and a rule may not invent the verdict.
        """
        table = data.get(grok.PERMISSION_TABLE)
        if not isinstance(table, dict):
            return []

        violations: List[RuleViolation] = []
        # Document order, so a file with two defects reads top to bottom.
        lists = [str(key) for key in table if str(key) in grok.PERMISSION_LIST_KEYS]
        for key in lists:
            if not isinstance(table[key], list):
                violations.append(
                    self._warn(
                        block,
                        f"[{grok.PERMISSION_TABLE}] '{key}' must be an array of rule "
                        f"strings, got {_type_name(table[key])}",
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
        return violations

    def _warn(self, block: GrokConfigBlock, message: str) -> RuleViolation:
        """A defect that costs one server or one key, never the file.

        Hardcoded, because the severity is the blast radius rather than the
        rule's verdict: the tables beside it still load whatever the
        author configures this rule to.
        """
        return self.violation(message, file_path=block.path, severity=Severity.WARNING)


def _server_problems(config: Dict[str, Any]) -> List[str]:
    """Why Grok refuses to load one ``[mcp_servers.<name>]`` table.

    The connection comes first and alone: a server with nothing to start is
    dropped whatever else it declares, and the reason names the field that
    should have carried it. Only a server Grok does start reaches the field
    types, where the remaining connection field is checked too — a ``url``
    beside a working ``command`` is deserialized just the same.
    """
    if grok.mcp_transport(config) is None:
        return [_connection_problem(config)]
    problems = []
    for field in _TYPED_SERVER_FIELDS:
        if field not in config:
            continue
        problem = _field_problem(field, config[field])
        if problem is not None:
            problems.append(problem)
    return problems


def _connection_problem(config: Dict[str, Any]) -> str:
    """Which field failed to name something Grok can start."""
    for field in ("command", "url"):
        if field not in config:
            continue
        value = config[field]
        if not isinstance(value, str):
            return f"'{field}' must be a string, got {_type_name(value)}"
        if not value.strip():
            return f"'{field}' is empty"
    return "declares neither 'command' nor 'url'"


def _field_problem(field: str, value: Any) -> Optional[str]:
    """How *value* fails the TOML type Grok reads *field* as, if it does."""
    if field in ("command", "url"):
        if isinstance(value, str):
            return None
        return f"'{field}' must be a string, got {_type_name(value)}"
    if field == "args":
        if not isinstance(value, list):
            return f"'args' must be an array of strings, got {_type_name(value)}"
        if any(not isinstance(item, str) for item in value):
            return "'args' must be an array of strings"
        return None
    if not isinstance(value, dict):
        return f"'{field}' must be a table of strings, got {_type_name(value)}"
    for key, item in value.items():
        if not isinstance(item, str):
            return (
                f"'{field}' value for '{safe_display(str(key))}' must be a string, "
                f"got {_type_name(item)}"
            )
    return None


def _type_name(value: Any) -> str:
    """The TOML type *value* was read as, in the spelling TOML uses."""
    return {
        bool: "boolean",
        dict: "table",
        float: "float",
        int: "integer",
        list: "array",
        str: "string",
    }.get(type(value), type(value).__name__)


def _and_list(names: List[str]) -> str:
    """*names* quoted and joined, with the verb the count needs."""
    quoted = [f"'{name}'" for name in names]
    if len(quoted) == 1:
        return f"{quoted[0]} is"
    return f"{', '.join(quoted[:-1])} and {quoted[-1]} are"
