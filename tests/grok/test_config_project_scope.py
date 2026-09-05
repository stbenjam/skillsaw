"""``grok-config-project-scope`` — what a project ``config.toml`` cannot contribute.

Grok reads one ``config.toml`` at four layers and a checkout's file is the
narrow one: ``[mcp_servers]``, ``[permission]``, ``[plugins]`` and ``[mcp]
max_output_bytes``, and nothing else. Refusals were measured against Grok Build 1.0.13 with positive user-scope
controls. Project plugin paths follow the pinned live-session resolver;
inspect does not expose that merge.

The silence is the point. ``configWarnings`` is a user-layer diagnostic, so
no observable Grok offers mentions an ignored table, an ignored key, or a
table name spelled the way another host spells it.
"""

from __future__ import annotations

import pytest

from skillsaw.blocks import GrokConfigBlock
from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formats import grok
from skillsaw.linter import Linter
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokConfigProjectScopeRule
from tests.grok._helpers import (
    copy_fixture,
    lint_json,
    messages,
    repo_with_config,
    run_rule,
    violations_for,
    where,
    write_repo,
)

#: A project file that contributes everything it declares, so a finding
#: beside it is about the table under test and nothing else.
HONORED = """\
[mcp_servers.berths]
command = "bin/harbourmaster"

[permission]
allow = ["Bash(make test)"]
"""


def check(repo, config=None):
    return run_rule(GrokConfigProjectScopeRule, repo, config)


def scope(tmp_path, body, name="repo"):
    return repo_with_config(tmp_path, name, body)


# ── Rule metadata ────────────────────────────────────────────────


def test_rule_metadata() -> None:
    rule = GrokConfigProjectScopeRule()

    assert rule.rule_id == "grok-config-project-scope"
    assert rule.default_severity() == Severity.WARNING
    assert rule.default_enabled == "auto"
    assert rule.since == "0.20.0"
    assert rule.repo_types == frozenset({RepositoryType.GROK_PROJECT})
    assert rule.provenance_scope is None
    assert not rule.supports_autofix
    assert "extra-tables" in rule.config_schema


def test_generated_defaults_match_the_class() -> None:
    defaults = LinterConfig.default().get_rule_config("grok-config-project-scope")

    assert defaults["enabled"] == "auto"
    assert defaults["severity"] == "warning"


def test_the_rule_is_not_loaded_without_grok_evidence(tmp_path) -> None:
    repo = write_repo(tmp_path / "no-grok")
    context = RepositoryContext(repo)

    assert RepositoryType.GROK_PROJECT not in context.repo_types
    loaded = {rule.rule_id for rule in Linter(context, no_plugins=True).rules}
    assert "grok-config-project-scope" not in loaded
    assert GrokConfigProjectScopeRule().check(context) == []


# ── The fixtures ─────────────────────────────────────────────────


def test_a_project_scoped_config_reports_nothing(tmp_path) -> None:
    repo = copy_fixture("grok/config-clean", tmp_path)

    # Pinned, or a regression in attachment would make this pass vacuously.
    assert RepositoryContext(repo).lint_tree.find(GrokConfigBlock)
    assert check(repo) == []


@pytest.fixture
def broken(tmp_path):
    repo = copy_fixture("grok/config-broken", tmp_path)
    return repo, check(repo)


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (
            "packages/bollard/.grok/config.toml",
            "[mcp.servers] loads no server; MCP servers are declared as [mcp_servers.<name>]",
        ),
        (
            "packages/dredger/.grok/config.toml",
            "[mcp-servers] loads no server; MCP servers are declared as [mcp_servers.<name>]",
        ),
        (
            "packages/lockgate/.grok/config.toml",
            "[permissions] loads nothing; the table is [permission]",
        ),
        (
            "packages/manifest/.grok/config.toml",
            "[model] is ignored in a project config.toml",
        ),
        (
            "packages/mooring/.grok/config.toml",
            "[hooks] is ignored in a project config.toml; "
            "project hooks live in .grok/hooks/*.json",
        ),
        (
            "packages/reefer/.grok/config.toml",
            "[mcp_servers.reefer] sets 'transport', which Grok ignores; the field is 'type'",
        ),
    ],
)
def test_each_defect_is_reported_once(broken, path, message) -> None:
    repo, violations = broken
    matched = [v for v in violations if v.message == message]

    assert len(matched) == 1, messages(violations)
    assert matched[0].severity == Severity.WARNING
    assert where(repo, matched[0]) == path


def test_the_broken_fixture_reports_nothing_else(broken) -> None:
    """The count is a noise gate: a new check must land in this fixture."""
    _, violations = broken

    assert len(violations) == 6, messages(violations)


# ── Ignored top-level tables and scalars ─────────────────────────


def test_one_ignored_table_is_named_on_its_own(tmp_path) -> None:
    repo = scope(tmp_path, HONORED + '\n[ui]\ntheme = "dark"\n')

    violations = check(repo)

    assert messages(violations) == ["[ui] is ignored in a project config.toml"]
    assert violations[0].severity == Severity.WARNING


def test_several_ignored_tables_are_one_consolidated_finding(tmp_path) -> None:
    """An author who wrote a user config into a project file wrote several
    tables, and naming each separately buries the run."""
    repo = scope(
        tmp_path,
        HONORED + '\n[ui]\ntheme = "dark"\n\n[telemetry]\nenabled = false\n\n[tools]\nweb = true\n',
    )

    assert messages(check(repo)) == [
        "[ui], [telemetry], [tools] are ignored in a project config.toml"
    ]


def test_the_consolidated_finding_is_capped(tmp_path) -> None:
    repo = scope(
        tmp_path,
        "[ui]\na = 1\n\n[tools]\na = 1\n\n[session]\na = 1\n\n[storage]\na = 1\n\n"
        "[voice]\na = 1\n",
    )

    assert messages(check(repo)) == [
        "[ui], [tools], [session], and 2 more are ignored in a project config.toml"
    ]


def test_a_top_level_scalar_is_not_written_as_a_table(tmp_path) -> None:
    """Calling ``disable_web_search`` a table would send the author looking
    for a header that is not there."""
    repo = scope(tmp_path, 'disable_web_search = true\ndisabled_mcp_tools = ["x"]\n')

    assert messages(check(repo)) == [
        "'disable_web_search', 'disabled_mcp_tools' are ignored in a project config.toml"
    ]


def test_an_array_of_tables_is_written_the_way_the_file_writes_it(tmp_path) -> None:
    repo = scope(tmp_path, '[[model_providers]]\nname = "xai"\n')

    assert messages(check(repo)) == ["[[model_providers]] is ignored in a project config.toml"]


def test_a_measured_refusal_names_the_file_to_write_instead(tmp_path) -> None:
    """Only ``hooks`` has somewhere else in the repository to go."""
    repo = scope(tmp_path, "[hooks]\nStop = []\n", "hooks")

    assert messages(check(repo)) == [
        "[hooks] is ignored in a project config.toml; " "project hooks live in .grok/hooks/*.json"
    ]


@pytest.mark.parametrize("table", ["skills", "sandbox"])
def test_a_refusal_honored_only_at_user_scope_carries_no_hint(tmp_path, table) -> None:
    """Which scope honors it is a consequence of the finding rather
    than a fix for it, and belongs on the rule's page."""
    repo = scope(tmp_path, f'[{table}]\npaths = ["./elsewhere"]\n', table)

    assert messages(check(repo)) == [f"[{table}] is ignored in a project config.toml"]


def test_a_measured_refusal_is_not_folded_into_the_consolidated_finding(tmp_path) -> None:
    """Its hint is the whole reason it is worth a finding of its own."""
    repo = scope(tmp_path, '[hooks]\nStop = []\n\n[ui]\ntheme = "dark"\n')

    assert messages(check(repo)) == [
        "[hooks] is ignored in a project config.toml; project hooks live in .grok/hooks/*.json",
        "[ui] is ignored in a project config.toml",
    ]


def test_every_hint_belongs_to_a_measured_refusal() -> None:
    """A hint may only be attached to a table a project file was measured
    to refuse; anything else would advise a move nobody needs to make."""
    from skillsaw.rules.builtin.grok.config_project_scope import _REFUSED_HINTS

    assert set(_REFUSED_HINTS) <= set(grok.PROJECT_CONFIG_TABLES_REFUSED)


# ── Keys inside an honored table ────────────────────────────────


def test_trusted_project_plugin_paths_are_supported(tmp_path) -> None:
    """The live session resolver merges these, unlike the inspect consumer."""
    repo = copy_fixture("grok/config-project-plugins", tmp_path)
    blocks = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)
    assert len(blocks) == 1
    assert blocks[0].raw_data["plugins"]["paths"] == ["./plugins/soleur"]
    assert [server.name for server in blocks[0].servers] == ["canary"]
    assert check(repo) == []
    report = lint_json(
        repo,
        "--rule",
        "grok-config-project-scope",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert violations_for(report, "grok-config-project-scope") == []


@pytest.mark.parametrize(
    "body",
    [
        "[plugins]\nautoupdate = true\n",
        "[mcp]\nmax_output_bytes = 65536\ntimeout = 30\n",
    ],
)
def test_an_unmeasured_key_inside_an_honored_table_is_not_reported(tmp_path, body) -> None:
    """Nothing was measured in either direction for these, and
    ``extra-tables`` reaches top-level names only — so a Grok release adding
    a key would leave a working config carrying a finding it cannot answer."""
    assert check(scope(tmp_path, body)) == []


# ── Spellings that load nothing ──────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        # An array of tables under [mcp].
        '[[mcp.servers]]\nname = "bollard"\ncommand = "bin/bollard"\n',
        # And the plain table spelling of the same misreading.
        '[mcp.servers.bollard]\ncommand = "bin/bollard"\n',
    ],
)
def test_servers_under_the_mcp_table_load_nothing(tmp_path, body) -> None:
    assert messages(check(scope(tmp_path, body))) == [
        "[mcp.servers] loads no server; MCP servers are declared as [mcp_servers.<name>]"
    ]


def test_a_misspelled_servers_table_is_not_also_an_unknown_mcp_key(tmp_path) -> None:
    """One defect, one finding: ``servers`` is the misreading, not a second
    key ``[mcp]`` does not contribute."""
    violations = check(scope(tmp_path, '[[mcp.servers]]\ncommand = "bin/bollard"\n'))

    assert len(violations) == 1


@pytest.mark.parametrize("table", sorted(grok.MCP_SERVERS_MISSPELLED_TABLES))
def test_a_misspelled_top_level_servers_table(tmp_path, table) -> None:
    repo = scope(tmp_path, f'[{table}.dredger]\ncommand = "bin/dredger"\n', table)

    assert messages(check(repo)) == [
        f"[{table}] loads no server; MCP servers are declared as [mcp_servers.<name>]"
    ]


def test_the_plural_permission_table(tmp_path) -> None:
    """It loads nothing, and the file drops out of ``permissions.sources``
    entirely, so nothing marks its absence."""
    repo = scope(tmp_path, '[permissions]\nallow = ["Bash(make test)"]\n')

    assert messages(check(repo)) == ["[permissions] loads nothing; the table is [permission]"]


def test_transport_inside_a_server(tmp_path) -> None:
    """Not an alias for ``type``: Grok reports it unrecognized and ignores
    it, and the server loads from whatever ``command`` says."""
    repo = scope(tmp_path, '[mcp_servers.reefer]\ntransport = "stdio"\ncommand = "bin/reefer"\n')

    assert messages(check(repo)) == [
        "[mcp_servers.reefer] sets 'transport', which Grok ignores; the field is 'type'"
    ]


def test_transport_is_reported_per_server(tmp_path) -> None:
    repo = scope(
        tmp_path,
        '[mcp_servers.reefer]\ntransport = "stdio"\ncommand = "bin/reefer"\n\n'
        '[mcp_servers.tugs]\ntransport = "http"\nurl = "https://tugs.example/mcp"\n',
    )

    assert messages(check(repo)) == [
        "[mcp_servers.reefer] sets 'transport', which Grok ignores; the field is 'type'",
        "[mcp_servers.tugs] sets 'transport', which Grok ignores; the field is 'type'",
    ]


def test_default_mode_inside_the_permission_table(tmp_path) -> None:
    repo = scope(tmp_path, '[permission]\nallow = []\ndefaultMode = "acceptEdits"\n')

    assert messages(check(repo)) == [
        "[permission] 'defaultMode' is a .claude/settings.json key, which Grok ignores"
    ]


# ── What is never reported ───────────────────────────────────────


def test_the_honored_tables_are_never_reported(tmp_path) -> None:
    """All four, including the two carried on the reference's word: reporting
    a table the documentation endorses would be a false positive."""
    repo = scope(
        tmp_path,
        HONORED + '\n[plugins]\nenabled = ["tide-charts"]\ndisabled = ["old"]\n'
        "\n[mcp]\nmax_output_bytes = 65536\n",
    )

    assert check(repo) == []


def test_a_documented_type_spelling_inside_a_server_is_not_a_misspelling(tmp_path) -> None:
    repo = scope(tmp_path, '[mcp_servers.tideboard]\ntype = "sse"\nurl = "https://x.example/mcp"\n')

    assert check(repo) == []


def test_a_malformed_file_has_no_scope_to_report(tmp_path) -> None:
    """A file Grok refuses to parse contributes nothing at all, and
    ``grok-config-valid`` reports it."""
    repo = scope(tmp_path, '[model]\nname = "grok-4"\n\n[ui]\nbroken = \n')

    assert check(repo) == []


def test_a_server_whose_value_is_not_a_table_is_not_read_for_transport(tmp_path) -> None:
    """``grok-config-valid`` owns that shape; this rule must not raise over
    it while looking for a misspelled field."""
    repo = scope(tmp_path, '[mcp_servers]\ngantry = "bin/gantry"\n')

    assert check(repo) == []


# ── The ``extra-tables`` option ──────────────────────────────────


def test_extra_tables_accepts_a_table_a_newer_grok_honors(tmp_path) -> None:
    repo = scope(tmp_path, '[toolset]\nname = "harbour"\n')

    assert messages(check(repo)) == ["[toolset] is ignored in a project config.toml"]
    assert check(repo, {"extra-tables": ["toolset"]}) == []


def test_extra_tables_does_not_silence_the_rest(tmp_path) -> None:
    repo = scope(tmp_path, '[toolset]\nname = "harbour"\n\n[ui]\ntheme = "dark"\n')

    assert messages(check(repo, {"extra-tables": ["toolset"]})) == [
        "[ui] is ignored in a project config.toml"
    ]


def test_extra_tables_can_accept_a_spelling_that_used_to_load_nothing(tmp_path) -> None:
    """A release that starts honoring one of the misspelled table names
    must be nameable here, or the rule reports a file that works."""
    repo = scope(tmp_path, '[mcpServers.dredger]\ncommand = "bin/dredger"\n')

    assert check(repo, {"extra-tables": ["mcpServers"]}) == []


@pytest.mark.parametrize("value", [42, "toolset", None, {"toolset": True}])
def test_a_wrong_typed_extra_tables_costs_no_findings(tmp_path, value) -> None:
    """The declared type is not enforced when the config loads. Iterating a
    bad value would raise and cost every finding in every config file over
    one bad config line."""
    repo = scope(tmp_path, '[ui]\ntheme = "dark"\n')

    assert messages(check(repo, {"extra-tables": value})) == [
        "[ui] is ignored in a project config.toml"
    ]


def test_a_non_string_entry_in_extra_tables_is_skipped(tmp_path) -> None:
    repo = scope(tmp_path, '[toolset]\nname = "harbour"\n')

    assert check(repo, {"extra-tables": [42, "toolset"]}) == []


# ── Configured severity ──────────────────────────────────────────


def test_a_configured_severity_moves_every_finding(tmp_path) -> None:
    """Every finding is the same defect at the same cost — something the
    author wrote that the file cannot contribute — so none of them is pinned
    against the user's override."""
    repo = copy_fixture("grok/config-broken", tmp_path)
    (repo / ".skillsaw.yaml").write_text(
        'version: "99.0.0"\nrules:\n  grok-config-project-scope:\n    severity: info\n'
    )

    found = violations_for(lint_json(repo, returncode=1), "grok-config-project-scope")

    assert len(found) == 6
    assert {v["severity"] for v in found} == {"info"}
