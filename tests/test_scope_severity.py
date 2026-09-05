"""Explicit overrides apply to primary entry failures without changing defaults."""

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.rule import Severity
from skillsaw.rules.builtin.antigravity.mcp_valid import AntigravityMcpValidRule
from skillsaw.rules.builtin.grok.config_valid import GrokConfigValidRule
from tests.test_integration import copy_fixture

CASES = [
    ("antigravity-mcp-valid", AntigravityMcpValidRule),
    ("grok-config-valid", GrokConfigValidRule),
]


def _config(rules):
    return LinterConfig(version="99.0.0", rules=rules)


@pytest.mark.parametrize("rule_id,rule_class", CASES)
@pytest.mark.parametrize("severity", [None, "info", "warning", "error"])
def test_direct_rule_and_linter_honor_explicit_scope_severity(
    tmp_path, rule_id, rule_class, severity
):
    repo = copy_fixture("config/scope-severity", tmp_path)
    settings = {"severity": severity}
    expected = Severity(severity) if severity else Severity.WARNING
    context = RepositoryContext(repo)
    direct = rule_class(settings).check(context)
    loaded = Linter(
        context,
        _config({rule_id: settings}),
        rule_ids={rule_id},
        no_custom_rules=True,
        no_plugins=True,
    ).run()
    assert len(direct) == len(loaded) == 1
    assert direct[0].severity == loaded[0].severity == expected


@pytest.mark.parametrize("rule_id,rule_class", CASES)
def test_implicit_defaults_and_independent_linters_keep_their_own_scope(
    tmp_path, rule_id, rule_class
):
    repo = copy_fixture("config/scope-severity", tmp_path)
    context = RepositoryContext(repo)
    configs = [None, LinterConfig.default(), _config({}), _config({rule_id: {"enabled": True}})]
    for config in configs:
        found = Linter(
            context, config, rule_ids={rule_id}, no_custom_rules=True, no_plugins=True
        ).run()
        assert len(found) == 1 and found[0].severity == Severity.WARNING
    info = Linter(
        context,
        _config({rule_id: {"severity": "info"}}),
        rule_ids={rule_id},
        no_custom_rules=True,
        no_plugins=True,
    )
    error = Linter(
        context,
        _config({rule_id: {"severity": "error"}}),
        rule_ids={rule_id},
        no_custom_rules=True,
        no_plugins=True,
    )
    assert [v.severity for v in info.run()] == [Severity.INFO]
    assert [v.severity for v in error.run()] == [Severity.ERROR]
    assert [v.severity for v in info.run()] == [Severity.INFO]


@pytest.mark.parametrize("rule_id,rule_class", CASES)
def test_changed_generated_default_is_an_override(tmp_path, rule_id, rule_class):
    repo = copy_fixture("config/scope-severity", tmp_path)
    config = LinterConfig.default()
    config.rules[rule_id]["severity"] = "info"
    found = Linter(
        RepositoryContext(repo), config, rule_ids={rule_id}, no_custom_rules=True, no_plugins=True
    ).run()
    assert [v.severity for v in found] == [Severity.INFO]
