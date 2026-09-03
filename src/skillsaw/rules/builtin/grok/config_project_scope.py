"""
Rule: grok-config-project-scope

``config.toml`` is one file read at four layers, and the project layer is
the narrow one: a ``.grok/config.toml`` in a checkout contributes
``[mcp_servers]``, ``[permission]``, ``[plugins]`` and ``[mcp]
max_output_bytes``, and everything else an author writes there is dropped.

Dropped in silence, which is the whole reason for the rule.
``configWarnings`` is a user-layer diagnostic, so no observable Grok offers
mentions an ignored table, an ignored key, or a table name spelled the way
another host spells it. The file loads, the tables Grok knows take effect,
and the rest is gone.

The honored set lives in ``skillsaw.formats.grok`` and holds both the
measured half and the documented half, because reporting a table the
reference endorses would be a false positive on a file the docs bless. What
the rule reports inside one of those tables is a measured refusal and
nothing else, for the same reason: an unknown-key finding there would rest
on no measurement and would fire on a working config the first time Grok
adds a key.

Only :class:`GrokConfigBlock` is iterated, a node type that exists only
where Grok's project layer does, so the rule declares no
``provenance_scope``.
"""

from typing import Any, Dict, List, Mapping, Set, Sized

from skillsaw.blocks import GrokConfigBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats import grok
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import sample

#: What a project file drops. One sentence, ending every finding, so the
#: verdict never has to be inferred from the table's name.
_IGNORED = "ignored in a project config.toml"

#: The file to write instead, for a refusal that has one. Keyed by the table
#: name, so a name added to ``PROJECT_CONFIG_TABLES_REFUSED`` upstream falls
#: back to the plain finding rather than borrowing another table's advice.
#:
#: Only ``hooks`` has somewhere else in the repository to go. ``skills`` and
#: ``sandbox`` are honored at user scope, which is a consequence of the
#: finding rather than a fix for it, and belongs on the rule's page.
_REFUSED_HINTS: Mapping[str, str] = {
    "hooks": "project hooks live in .grok/hooks/*.json",
}


class GrokConfigProjectScopeRule(Rule):
    """Report Grok Build configuration a project config.toml cannot contribute"""

    since = "0.20.0"

    repo_types = frozenset({RepositoryType.GROK_PROJECT})

    config_schema = {
        "extra-tables": {
            "type": "list",
            "default": [],
            "description": (
                "Additional top-level table names to accept, for tables a Grok "
                "release honors at project scope that this skillsaw release has "
                "not heard of"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "grok-config-project-scope"

    @property
    def description(self) -> str:
        return ".grok/config.toml must only carry settings a project file contributes"

    def default_severity(self) -> Severity:
        # The file loads and the setting does not, with no diagnostic
        # anywhere. Nothing breaks; something the author wrote is gone.
        return Severity.WARNING

    def _honored_tables(self) -> Set[str]:
        """The top-level names a project file contributes, plus any declared.

        The declared type is not enforced when the config loads, so
        ``extra-tables: 42`` arrives here as an int. Iterating it would
        raise ``TypeError`` and cost every finding in every config file
        over one bad config line.
        """
        known = set(grok.PROJECT_CONFIG_TABLES)
        extra = self.setting("extra-tables") or []
        if not isinstance(extra, (list, tuple, set, frozenset)):
            return known
        return known | {name for name in extra if isinstance(name, str)}

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        honored = self._honored_tables()

        for block in context.lint_tree.find(GrokConfigBlock):
            data = block.raw_data
            if data is None:
                # A file Grok refuses to parse contributes nothing at all,
                # and ``grok-config-valid`` reports it. Naming its tables
                # here would name a scope defect in a file with no scope.
                continue
            violations.extend(self._check_top_level(block, data, honored))
            violations.extend(self._check_refused_keys(block, data))
            violations.extend(self._check_mcp(block, data))
            violations.extend(self._check_servers(block))
            violations.extend(self._check_permission(block, data))

        return violations

    # -- Top-level tables and scalars -------------------------------

    def _check_top_level(
        self, block: GrokConfigBlock, data: Dict[str, Any], honored: Set[str]
    ) -> List[RuleViolation]:
        """Everything a project file drops outright, named once each."""
        violations: List[RuleViolation] = []
        plain: List[str] = []

        # No ``str()`` on a key: a TOML key is a string by grammar, unlike a
        # YAML one, so the defensiveness the YAML readers need is dead here.
        for key, value in data.items():
            if key in honored:
                continue
            if key in grok.MCP_SERVERS_MISSPELLED_TABLES:
                violations.append(
                    self._violation(
                        block,
                        f"[{safe_display(key)}] loads no server; MCP servers are declared "
                        f"as [{block.servers_key}.<name>]",
                    )
                )
            elif key == grok.PERMISSION_MISSPELLED_TABLE:
                violations.append(
                    self._violation(
                        block,
                        f"[{safe_display(key)}] loads nothing; the table is "
                        f"[{grok.PERMISSION_TABLE}]",
                    )
                )
            elif key in _REFUSED_HINTS and key in grok.PROJECT_CONFIG_TABLES_REFUSED:
                violations.append(
                    self._violation(
                        block,
                        f"{_render(key, value)} is {_IGNORED}; {_REFUSED_HINTS[key]}",
                    )
                )
            else:
                plain.append(_render(key, value))

        if plain:
            # One finding for the rest: an author who wrote a user config
            # into a project file wrote several tables, and naming each one
            # separately buries the run.
            violations.append(self._violation(block, f"{sample(plain)} {_verb(plain)} {_IGNORED}"))
        return violations

    # -- Keys inside an honored table -------------------------------

    def _check_refused_keys(
        self, block: GrokConfigBlock, data: Dict[str, Any]
    ) -> List[RuleViolation]:
        """Keys a project file drops from a table it otherwise honors.

        Measured refusals only, from
        :data:`~skillsaw.formats.grok.PROJECT_CONFIG_KEYS_REFUSED`. An
        unknown key inside one of these tables is not reported: nothing was
        measured in either direction, and ``extra-tables`` reaches top-level
        names only, so a Grok release adding a key would leave a working
        config carrying a finding with no way to answer it.
        """
        violations: List[RuleViolation] = []
        for table_name, refused in grok.PROJECT_CONFIG_KEYS_REFUSED.items():
            table = data.get(table_name)
            if not isinstance(table, dict):
                continue
            present = [f"'{key}'" for key in table if key in refused]
            if present:
                violations.append(
                    self._violation(
                        block, f"[{table_name}] {sample(present)} {_verb(present)} {_IGNORED}"
                    )
                )
        return violations

    # -- Misspellings inside an honored table -----------------------

    def _check_mcp(self, block: GrokConfigBlock, data: Dict[str, Any]) -> List[RuleViolation]:
        """``[mcp]`` holds one misspelling of the servers table."""
        table_name, servers_key = grok.MCP_SERVERS_MISSPELLING
        table = data.get(table_name)
        if not isinstance(table, dict) or servers_key not in table:
            return []
        return [
            self._violation(
                block,
                f"[{table_name}.{servers_key}] loads no server; MCP servers are "
                f"declared as [{block.servers_key}.<name>]",
            )
        ]

    def _check_servers(self, block: GrokConfigBlock) -> List[RuleViolation]:
        """``transport`` is the plausible misreading of a server's ``type``."""
        field = grok.MCP_TYPE_MISSPELLED_FIELD
        return [
            self._violation(
                block,
                f"[{block.servers_key}.{safe_display(name)}] sets '{field}', which "
                "Grok ignores; the field is 'type'",
            )
            for name, config in block.server_entries()
            if isinstance(config, dict) and field in config
        ]

    def _check_permission(
        self, block: GrokConfigBlock, data: Dict[str, Any]
    ) -> List[RuleViolation]:
        """``defaultMode`` is a ``.claude/settings.json`` key with no meaning here."""
        table = data.get(grok.PERMISSION_TABLE)
        if not isinstance(table, dict) or grok.PERMISSION_MISSPELLED_KEY not in table:
            return []
        return [
            self._violation(
                block,
                f"[{grok.PERMISSION_TABLE}] '{grok.PERMISSION_MISSPELLED_KEY}' is a "
                ".claude/settings.json key, which Grok ignores",
            )
        ]

    def _violation(self, block: GrokConfigBlock, message: str) -> RuleViolation:
        # No hardcoded severity: every finding here is the same defect —
        # something the author wrote that the file cannot contribute — so
        # a configured severity moves all of them together.
        return self.violation(message, file_path=block.path)


def _render(name: str, value: Any) -> str:
    """*name* written the way the file writes it.

    A table is ``[name]``, an array of tables ``[[name]]``, and a top-level
    scalar is a bare key — calling ``disable_web_search`` a table would send
    the author looking for a header that is not there.
    """
    display = safe_display(name)
    if isinstance(value, dict):
        return f"[{display}]"
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return f"[[{display}]]"
    return f"'{display}'"


def _verb(names: Sized) -> str:
    return "is" if len(names) == 1 else "are"
