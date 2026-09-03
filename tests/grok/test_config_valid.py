"""``grok-config-valid`` — one verdict per defect, at the severity its scope earns.

Every scope below was measured against Grok Build 1.0.13: a project
``.grok/config.toml`` built one defect at a time in a trusted checkout, read
back from ``grok inspect --json``, each case carrying a canary server and a
canary ``[permission]`` table so file scope, table scope and key scope are
told apart rather than assumed. ``skillsaw.formats.grok`` records the
verdicts; re-measure before changing one here.

The split that matters: Grok raises ``mcpConfigProblems`` for a server it
cannot load, and raises **nothing at all** for a ``[permission]`` table it
cannot read.
"""

from __future__ import annotations

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.linter import Linter
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokConfigValidRule
from tests.grok._helpers import (
    at,
    copy_fixture,
    lint_json,
    messages,
    only,
    repo_with_config,
    run_rule,
    violations_for,
    where,
    write_repo,
)

#: A server Grok loads, to sit beside the defect under test. Its presence is
#: what proves a per-server finding is per-server.
CANARY = '[mcp_servers.berths]\ncommand = "bin/harbourmaster"\n'


def check(repo):
    return run_rule(GrokConfigValidRule, repo)


def config(tmp_path, body, name="repo"):
    """A repository whose only Grok content is a ``config.toml`` of *body*."""
    return repo_with_config(tmp_path, name, body)


# ── Rule metadata ────────────────────────────────────────────────


def test_rule_metadata() -> None:
    rule = GrokConfigValidRule()

    assert rule.rule_id == "grok-config-valid"
    assert rule.default_severity() == Severity.ERROR
    assert rule.default_enabled == "auto"
    assert rule.since == "0.20.0"
    assert rule.repo_types == frozenset({RepositoryType.GROK_PROJECT})
    # A tool directory nobody else claims needs no provenance filtering.
    assert rule.provenance_scope is None
    assert not rule.supports_autofix
    # No tuneable settings: the honoured vocabulary is Grok's, and the one
    # place a release can widen it is the scope rule's ``extra-tables``.
    assert rule.config_schema == {}


def test_generated_defaults_match_the_class() -> None:
    config_defaults = LinterConfig.default().get_rule_config("grok-config-valid")

    assert config_defaults["enabled"] == "auto"
    assert config_defaults["severity"] == "error"


def test_the_rule_is_not_loaded_without_grok_evidence(tmp_path) -> None:
    repo = write_repo(tmp_path / "no-grok")
    context = RepositoryContext(repo)

    assert RepositoryType.GROK_PROJECT not in context.repo_types
    loaded = {rule.rule_id for rule in Linter(context, no_plugins=True).rules}
    assert "grok-config-valid" not in loaded
    assert GrokConfigValidRule().check(context) == []


def test_the_rule_runs_on_a_repository_with_a_project_config(tmp_path) -> None:
    repo = copy_fixture("grok/config-broken", tmp_path)

    loaded = {rule.rule_id for rule in Linter(RepositoryContext(repo), no_plugins=True).rules}

    assert "grok-config-valid" in loaded


# ── The clean fixture ────────────────────────────────────────────


def test_a_well_formed_project_config_reports_nothing(tmp_path) -> None:
    assert check(copy_fixture("grok/config-clean", tmp_path)) == []


def test_the_clean_fixture_lints_green(tmp_path) -> None:
    repo = copy_fixture("grok/config-clean", tmp_path)

    assert lint_json(repo)["violations"] == []


# ── The broken fixture: one defect per package ───────────────────


@pytest.fixture
def broken(tmp_path):
    repo = copy_fixture("grok/config-broken", tmp_path)
    return repo, check(repo)


#: Every finding the broken fixture makes, as (file, message, severity).
#: Severity is the blast radius: a parse error costs the whole file, and
#: everything under it costs one server or one key.
@pytest.mark.parametrize(
    ("path", "message", "severity"),
    [
        # Whole file: the unclosed array costs the [permission] table under
        # it, and Grok exits 0 without saying so.
        (
            ".grok/config.toml",
            "Invalid TOML: Unclosed array (at line 5, column 1)",
            Severity.ERROR,
        ),
        # A key set twice is a TOML parse error, so it costs the file too.
        (
            "packages/gantry/.grok/config.toml",
            "Invalid TOML: Cannot overwrite a value (at line 4, column 27)",
            Severity.ERROR,
        ),
        # Server scope: the sibling [mcp_servers.berths] still loads.
        (
            "packages/quayside/.grok/config.toml",
            "[mcp_servers.quayside] declares neither 'command' nor 'url'",
            Severity.WARNING,
        ),
        (
            "packages/tugs/.grok/config.toml",
            "[mcp_servers.tugs] 'command' is empty",
            Severity.WARNING,
        ),
        # Key scope, and the one Grok reports nowhere at any scope.
        (
            "packages/stevedore/.grok/config.toml",
            "[permission] 'rules' is discarded because 'allow' is also set",
            Severity.WARNING,
        ),
    ],
)
def test_each_defect_is_reported_once(broken, path, message, severity) -> None:
    """The whole message, not a fragment: a finding states the problem and
    the place, and says nothing else."""
    repo, violations = broken
    matched = [v for v in violations if v.message == message]

    assert len(matched) == 1, messages(violations)
    assert matched[0].severity == severity
    assert where(repo, matched[0]) == path


def test_the_broken_fixture_reports_nothing_else(broken) -> None:
    """The counts are a noise gate: a new check must land in this fixture."""
    _, violations = broken

    assert len(at(violations, Severity.ERROR)) == 2, messages(violations)
    assert len(at(violations, Severity.WARNING)) == 3, messages(violations)
    assert at(violations, Severity.INFO) == []


def test_the_broken_fixture_fires_both_config_rules(tmp_path) -> None:
    """What ``TestRuleCoverage`` needs from this fixture, asserted where the
    rule lives rather than only in the integration sweep."""
    repo = copy_fixture("grok/config-broken", tmp_path)

    fired = {v["rule_id"] for v in lint_json(repo, returncode=1)["violations"]}

    assert {"grok-config-valid", "grok-config-project-scope"} <= fired


# ── The whole file ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "body", "detail"),
    [
        # A syntax error.
        ("unclosed", '[mcp_servers.gantry]\nargs = ["mcp"\n', "Unclosed array"),
        # A key set twice in one table.
        (
            "duplicate-key",
            '[mcp_servers.gantry]\ncommand = "a"\ncommand = "b"\n',
            "Cannot overwrite a value",
        ),
        # A table header written twice.
        (
            "duplicate-table",
            '[mcp_servers.gantry]\ncommand = "a"\n\n[mcp_servers.gantry]\ncommand = "b"\n',
            "Cannot declare",
        ),
    ],
)
def test_a_malformed_file_is_one_finding_at_the_rule_severity(tmp_path, name, body, detail) -> None:
    """Grok loads nothing from the file, including the tables above the
    error, and the only trace it leaves is a note inside ``grok inspect``."""
    repo = config(tmp_path, body + "\n[permission]\nallow = []\n", name)

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].severity == Severity.ERROR
    assert violations[0].message.startswith("Invalid TOML: ")
    assert detail in violations[0].message


def test_a_malformed_file_reports_nothing_about_its_tables(tmp_path) -> None:
    """The file has a discarded ``rules`` array and an ignored table in it,
    and neither is a defect in a file Grok never parsed."""
    repo = config(
        tmp_path,
        "[permission]\nallow = []\nrules = []\n\n[model]\nname = 'grok-4'\nbroken = \n",
        "malformed-with-defects",
    )

    assert len(check(repo)) == 1


# ── ``[mcp_servers]`` ────────────────────────────────────────────


def test_a_non_table_mcp_servers_costs_that_table_only(tmp_path) -> None:
    repo = config(tmp_path, 'mcp_servers = "servers.json"\n\n[permission]\nallow = []\n')

    violations = check(repo)

    assert messages(violations) == ["'mcp_servers' must be a table of servers, got string"]
    assert violations[0].severity == Severity.WARNING


def test_a_server_entry_that_is_not_a_table(tmp_path) -> None:
    """``[mcp_servers]`` holding a bare scalar: Grok has no server table to
    read, and the sibling above it still loads."""
    repo = config(tmp_path, CANARY + '\n[mcp_servers]\ngantry = "bin/gantry"\n')

    violations = check(repo)

    assert messages(violations) == ["[mcp_servers.gantry] must be a table"]


@pytest.mark.parametrize(
    ("table", "reason"),
    [
        # Nothing to start at all.
        ('args = ["mcp"]\ncwd = "services/quayside"\n', "declares neither 'command' nor 'url'"),
        ("\n", "declares neither 'command' nor 'url'"),
        # Present, and naming nothing.
        ('command = ""\n', "'command' is empty"),
        ('command = "   "\n', "'command' is empty"),
        ('url = ""\n', "'url' is empty"),
        # Present, and not a string at all.
        ("command = 42\n", "'command' must be a string, got integer"),
        ('command = ["bin/gantry"]\n', "'command' must be a string, got array"),
        ("url = true\n", "'url' must be a string, got boolean"),
    ],
)
def test_a_server_grok_drops_is_one_finding_naming_the_reason(tmp_path, table, reason) -> None:
    """Per server and order-independent: the canary beside it still loads."""
    repo = config(tmp_path, CANARY + "\n[mcp_servers.quayside]\n" + table)

    violations = check(repo)

    assert messages(violations) == [f"[mcp_servers.quayside] {reason}"]
    assert violations[0].severity == Severity.WARNING


@pytest.mark.parametrize(
    ("table", "reason"),
    [
        ('args = "mcp"\n', "'args' must be an array of strings, got string"),
        ("args = 3\n", "'args' must be an array of strings, got integer"),
        ('args = ["mcp", 3]\n', "'args' must be an array of strings"),
        ('env = "PROFILE=readonly"\n', "'env' must be a table of strings, got string"),
        ("env = { PROFILE = 3 }\n", "'env' value for 'PROFILE' must be a string, got integer"),
        ("headers = 3\n", "'headers' must be a table of strings, got integer"),
        (
            "headers = { X-Terminal = true }\n",
            "'headers' value for 'X-Terminal' must be a string, got boolean",
        ),
    ],
)
def test_a_wrong_typed_server_field_costs_that_server(tmp_path, table, reason) -> None:
    """Grok's deserializer refuses the transport and drops the server;
    ``mcpConfigProblems`` calls it an invalid transport."""
    repo = config(tmp_path, CANARY + '\n[mcp_servers.quayside]\ncommand = "bin/quayside"\n' + table)

    violations = check(repo)

    assert messages(violations) == [f"[mcp_servers.quayside] {reason}"]


def test_the_other_connection_field_is_typed_too(tmp_path) -> None:
    """A ``command`` wins the transport, and the ``url`` beside it is still
    deserialized."""
    repo = config(tmp_path, '[mcp_servers.quayside]\ncommand = "bin/quayside"\nurl = 8080\n')

    assert messages(check(repo)) == ["[mcp_servers.quayside] 'url' must be a string, got integer"]


def test_two_defects_in_one_server_are_one_finding(tmp_path) -> None:
    """One defect, one finding: the defect is the server Grok drops, and the
    problems are the reasons it drops it."""
    repo = config(
        tmp_path,
        '[mcp_servers.quayside]\ncommand = "bin/quayside"\nargs = 3\nenv = 4\n',
    )

    assert messages(check(repo)) == [
        "[mcp_servers.quayside] 'args' must be an array of strings, got integer, "
        "'env' must be a table of strings, got integer"
    ]


# ── ``[permission]`` ─────────────────────────────────────────────


@pytest.mark.parametrize("key", ["allow", "deny", "ask"])
def test_a_non_array_list_key_costs_that_key(tmp_path, key) -> None:
    """Nothing in Grok reports this, at any scope."""
    repo = config(tmp_path, f'[permission]\n{key} = "Bash(make test)"\n')

    violations = check(repo)

    assert messages(violations) == [
        f"[permission] '{key}' must be an array of rule strings, got string"
    ]
    assert violations[0].severity == Severity.WARNING


def test_each_non_array_list_key_is_its_own_finding(tmp_path) -> None:
    """Each key is read independently, so each is a defect of its own — and
    they are named in the order the file writes them."""
    repo = config(tmp_path, "[permission]\ndeny = 1\nallow = 2\n")

    assert messages(check(repo)) == [
        "[permission] 'deny' must be an array of rule strings, got integer",
        "[permission] 'allow' must be an array of rule strings, got integer",
    ]


def test_a_non_array_rules_costs_that_key(tmp_path) -> None:
    repo = config(tmp_path, '[permission]\nrules = "deny Bash"\n')

    assert messages(check(repo)) == ["[permission] 'rules' must be an array of tables, got string"]


@pytest.mark.parametrize("key", ["allow", "deny", "ask"])
def test_rules_beside_a_list_key_is_discarded_entirely(tmp_path, key) -> None:
    """Measured: every verbose rule is discarded whenever any of the three
    list keys is present, in any order, and nothing says so."""
    repo = config(
        tmp_path,
        f'[permission]\n{key} = ["Bash(make test)"]\n'
        'rules = [{ action = "deny", tool = "Bash", pattern = "psql *" }]\n',
    )

    violations = check(repo)

    assert messages(violations) == [
        f"[permission] 'rules' is discarded because '{key}' is also set"
    ]
    assert violations[0].severity == Severity.WARNING


def test_the_discard_is_order_independent(tmp_path) -> None:
    repo = config(
        tmp_path,
        '[permission]\nrules = [{ action = "deny", tool = "Bash" }]\nask = ["Bash(rm *)"]\n',
    )

    assert messages(check(repo)) == ["[permission] 'rules' is discarded because 'ask' is also set"]


def test_the_discard_names_every_list_key_that_causes_it(tmp_path) -> None:
    repo = config(
        tmp_path,
        '[permission]\nallow = []\ndeny = []\nask = []\nrules = [{ action = "deny" }]\n',
    )

    assert messages(check(repo)) == [
        "[permission] 'rules' is discarded because 'allow', 'deny' and 'ask' are also set"
    ]


def test_a_discarded_rules_is_not_also_reported_for_its_type(tmp_path) -> None:
    """One defect, one finding: once ``rules`` is gone, its type is not a
    second thing to fix."""
    repo = config(tmp_path, '[permission]\nallow = []\nrules = "deny Bash"\n')

    assert messages(check(repo)) == [
        "[permission] 'rules' is discarded because 'allow' is also set"
    ]


# ── What is never reported ───────────────────────────────────────


def test_an_unknown_server_field_is_not_a_defect(tmp_path) -> None:
    """Grok warns through ``mcpConfigProblems`` and loads the server anyway,
    so calling the file broken over it would be a false positive."""
    repo = config(
        tmp_path,
        '[mcp_servers.berths]\ncommand = "bin/harbourmaster"\nwibble = "nonsense"\n',
    )

    assert check(repo) == []


def test_a_known_but_unchecked_server_field_is_left_alone(tmp_path) -> None:
    """Every field in ``MCP_SERVER_FIELDS`` this rule does not type-check is
    vocabulary, not a shape to enforce."""
    repo = config(
        tmp_path,
        '[mcp_servers.berths]\ncommand = "bin/harbourmaster"\ncwd = "services/berths"\n'
        "startup_timeout_sec = 30\nexpose_image_base64 = true\n"
        'oauth_scopes = ["read"]\n',
    )

    assert check(repo) == []


def test_an_unknown_permission_key_is_not_a_defect(tmp_path) -> None:
    """``grok-config-project-scope`` owns the spelling that is a mistake."""
    repo = config(tmp_path, '[permission]\nallow = []\ndefaultMode = "acceptEdits"\n')

    assert check(repo) == []


def test_the_content_of_a_command_or_url_is_never_validated(tmp_path) -> None:
    """Grok validates neither: ``url = "not a url"`` loads as HTTP."""
    repo = config(tmp_path, '[mcp_servers.tideboard]\nurl = "not a url"\n')

    assert check(repo) == []


def test_a_disabled_server_is_not_a_defect(tmp_path) -> None:
    repo = config(
        tmp_path,
        '[mcp_servers.berths]\ncommand = "bin/harbourmaster"\nenabled = false\n',
    )

    assert check(repo) == []


def test_an_ignored_table_is_not_this_rule(tmp_path) -> None:
    """Scope belongs to ``grok-config-project-scope``; this rule reads the
    shape of the tables Grok does load."""
    repo = config(tmp_path, CANARY + '\n[model]\nname = "grok-4"\n')

    assert check(repo) == []


def test_a_non_table_permission_is_not_reported(tmp_path) -> None:
    """What it costs was never measured, and a rule may not invent a verdict
    to fill the gap."""
    repo = config(tmp_path, 'permission = "allow-all"\n')

    assert check(repo) == []


def test_an_empty_config_is_not_a_defect(tmp_path) -> None:
    """A file holding only comments parses to an empty table."""
    repo = config(tmp_path, "# Nothing to declare yet.\n")

    assert check(repo) == []


# ── Configured severity ──────────────────────────────────────────


def test_a_configured_severity_moves_the_file_scoped_findings_only(tmp_path) -> None:
    """The ERRORs follow the user's override; the per-server and per-key
    WARNINGs are the rule's verdict on blast radius, not its severity, and
    stay put whatever the user configures."""
    repo = copy_fixture("grok/config-broken", tmp_path)
    (repo / ".skillsaw.yaml").write_text(
        'version: "99.0.0"\nrules:\n  grok-config-valid:\n    severity: info\n'
    )

    found = violations_for(lint_json(repo, returncode=0), "grok-config-valid")

    assert {v["severity"] for v in found} == {"info", "warning"}
    assert len([v for v in found if v["severity"] == "info"]) == 2
    assert len([v for v in found if v["severity"] == "warning"]) == 3


def test_the_rule_can_be_turned_off(tmp_path) -> None:
    repo = copy_fixture("grok/config-broken", tmp_path)
    (repo / ".skillsaw.yaml").write_text(
        'version: "99.0.0"\nrules:\n  grok-config-valid:\n    enabled: false\n'
    )

    report = lint_json(repo, returncode=0)

    assert violations_for(report, "grok-config-valid") == []
    assert violations_for(report, "grok-config-project-scope")


# ── A package is a project of its own ────────────────────────────


def test_each_package_config_is_reported_at_its_own_path(tmp_path) -> None:
    """Grok reads the layer of the directory it is started in, so a package's
    defect belongs to the package, not to the repository root."""
    repo = copy_fixture("grok/config-broken", tmp_path)

    violations = check(repo)

    assert where(repo, only(violations, "[mcp_servers.tugs]")) == (
        "packages/tugs/.grok/config.toml"
    )
