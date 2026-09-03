"""Tests for rule aliases (legacy names) and rule deprecation.

0.18.0 renamed the Claude-format rules to ``claude-`` prefixed IDs and
deprecated four rules. Legacy names must keep working everywhere a rule is
named: config keys, --rule/--skip-rule, inline suppression directives, and
baselines. Deprecated rules stop running under ``enabled: auto`` and warn
when still referenced.
"""

import json
import shutil
from pathlib import Path

import pytest

from skillsaw.baseline import (
    BaselineEntry,
    BaselineFile,
    filter_baselined_violations,
    fingerprint_violation,
)
from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.rule import RuleViolation, Severity
from skillsaw.rules.builtin import (
    BUILTIN_RULE_REGISTRY,
    RULE_ALIASES,
    canonical_rule_id,
    rule_aliases,
    rule_baseline_aliases,
)
from skillsaw.suppression import build_suppression_map_for_file
from tests.cli_runner import run_cli


@pytest.fixture
def plugin_repo(tmp_path):
    """Minimal Claude plugin missing a README (claude-plugin-readme fires)."""
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "billing-tools",
                "description": "Commands for the billing dashboard",
                "version": "1.0.0",
            }
        )
    )
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "report.md").write_text(
        "---\ndescription: Generate the weekly billing report\n---\n\n"
        "# Report\n\nCollect the week's invoices and produce the summary table.\n"
    )
    return tmp_path


# ── Alias registry ──────────────────────────────────────────────


def test_every_alias_resolves_to_a_registered_rule():
    for alias, canonical in RULE_ALIASES.items():
        assert alias not in BUILTIN_RULE_REGISTRY
        assert canonical in BUILTIN_RULE_REGISTRY


def test_canonical_rule_id_passthrough_for_unknown_names():
    assert canonical_rule_id("not-a-rule") == "not-a-rule"
    assert canonical_rule_id("claude-plugin-readme") == "claude-plugin-readme"


def test_renamed_rules_carry_their_legacy_alias():
    expected = {
        "plugin-json-required": "claude-plugin-json-required",
        "plugin-json-valid": "claude-plugin-json-valid",
        "plugin-naming": "claude-plugin-naming",
        "plugin-readme": "claude-plugin-readme",
        "marketplace-json-valid": "claude-marketplace-json-valid",
        "marketplace-registration": "claude-marketplace-registration",
        "agent-frontmatter": "claude-agent-frontmatter",
        "command-frontmatter": "claude-command-frontmatter",
        "command-naming": "claude-command-naming",
        "command-name-format": "claude-command-name-format",
        "command-sections": "claude-command-sections",
        "settings-dangerous": "claude-settings-dangerous",
        "hooks-json-valid": "claude-hooks-valid",
        "rules-valid": "claude-rules-valid",
    }
    assert RULE_ALIASES == expected
    for alias, canonical in expected.items():
        assert rule_aliases(canonical) == (alias,)


# ── Config keys ─────────────────────────────────────────────────


def test_config_normalizes_legacy_rule_names(tmp_path):
    config_path = tmp_path / ".skillsaw.yaml"
    config_path.write_text('version: "99.0.0"\nrules:\n  plugin-readme:\n    severity: error\n')
    config = LinterConfig.from_file(config_path)
    assert "plugin-readme" not in config.rules
    assert config.rules["claude-plugin-readme"]["severity"] == "error"


def test_config_canonical_entry_wins_over_alias(tmp_path):
    config_path = tmp_path / ".skillsaw.yaml"
    config_path.write_text(
        'version: "99.0.0"\n'
        "rules:\n"
        "  plugin-readme:\n"
        "    severity: info\n"
        "  claude-plugin-readme:\n"
        "    severity: error\n"
    )
    config = LinterConfig.from_file(config_path)
    assert config.rules["claude-plugin-readme"]["severity"] == "error"
    assert any("plugin-readme" in w for w in config.warnings)


def test_legacy_config_key_disables_renamed_rule(plugin_repo):
    config_path = plugin_repo / ".skillsaw.yaml"
    config_path.write_text('version: "99.0.0"\nrules:\n  plugin-readme:\n    enabled: false\n')
    config = LinterConfig.from_file(config_path)
    context = RepositoryContext(plugin_repo)
    linter = Linter(context, config=config, no_plugins=True)
    results = linter.run()
    assert "claude-plugin-readme" not in {r.rule_id for r in linter.rules}
    assert "claude-plugin-readme" not in {v.rule_id for v in results}
    # No invalid-config warning: the legacy name is not an unknown rule.
    assert "invalid-config" not in {v.rule_id for v in results}


def test_legacy_hooks_key_configures_the_renamed_hooks_rule(tmp_path):
    """0.20.0 split ``hooks-json-valid`` per host: Claude Code's half kept
    the checks under ``claude-hooks-valid``, and a config written against
    the old name must still reach it."""
    config_path = tmp_path / ".skillsaw.yaml"
    config_path.write_text(
        'version: "99.0.0"\nrules:\n  hooks-json-valid:\n    severity: warning\n'
    )
    config = LinterConfig.from_file(config_path)
    assert "hooks-json-valid" not in config.rules
    assert config.rules["claude-hooks-valid"]["severity"] == "warning"


def test_legacy_hooks_key_lowers_the_severity_of_a_real_finding(tmp_path):
    """End to end, not just the config table: a Claude plugin's malformed
    hooks file must be reported at the severity the legacy key sets."""
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "billing-tools",
                "description": "Commands for the billing dashboard",
                "version": "1.0.0",
            }
        )
    )
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "hooks.json").write_text(
        json.dumps({"hooks": {"PostToolUse": {"command": "npm run lint"}}})
    )
    config_path = tmp_path / ".skillsaw.yaml"
    config_path.write_text(
        'version: "99.0.0"\nrules:\n  hooks-json-valid:\n    severity: warning\n'
    )

    results = Linter(
        RepositoryContext(tmp_path), config=LinterConfig.from_file(config_path), no_plugins=True
    ).run()
    found = [v for v in results if v.rule_id == "claude-hooks-valid"]
    assert found, [v.rule_id for v in results]
    assert all(v.severity is Severity.WARNING for v in found)


# ── --rule / --skip-rule ────────────────────────────────────────


def test_rule_flag_accepts_legacy_name(plugin_repo):
    context = RepositoryContext(plugin_repo)
    linter = Linter(context, rule_ids={"plugin-readme"}, no_plugins=True)
    assert {r.rule_id for r in linter.rules} == {"claude-plugin-readme"}
    assert any(v.rule_id == "claude-plugin-readme" for v in linter.run())


def test_skip_rule_flag_accepts_legacy_name(plugin_repo):
    context = RepositoryContext(plugin_repo)
    linter = Linter(context, skip_rule_ids={"plugin-readme"}, no_plugins=True)
    assert "claude-plugin-readme" not in {r.rule_id for r in linter.rules}


# ── Inline suppression directives ───────────────────────────────


def test_suppression_directive_with_legacy_name(tmp_path):
    md = tmp_path / "GUIDE.md"
    md.write_text(
        "# Guide\n\n"
        "<!-- skillsaw-disable-next-line command-naming -->\n"
        "Some line the legacy directive suppresses.\n"
    )
    smap = build_suppression_map_for_file(md)
    assert smap is not None
    assert smap.is_suppressed("claude-command-naming", 4)
    assert not smap.is_suppressed("claude-command-naming", 2)


# ── Baselines ───────────────────────────────────────────────────


def test_baseline_with_legacy_rule_id_still_suppresses(tmp_path):
    """A baseline generated before the rename keeps matching."""
    plugin_dir = tmp_path / "plugins" / "billing"
    plugin_dir.mkdir(parents=True)
    violation = RuleViolation(
        rule_id="claude-plugin-readme",
        severity=Severity.WARNING,
        message="Missing README.md (recommended)",
        file_path=plugin_dir / "README.md",
    )
    legacy_fp = fingerprint_violation(violation, tmp_path, _rule_id="plugin-readme")
    baseline = BaselineFile(
        version="1",
        generated_by="skillsaw 0.17.0",
        generated_at="2026-01-01T00:00:00+00:00",
        violations=[
            BaselineEntry(
                fingerprint=legacy_fp,
                rule_id="plugin-readme",
                file_path="plugins/billing/README.md",
                line=None,
                message="Missing README.md (recommended)",
                severity="warning",
            )
        ],
        root_path=tmp_path,
    )
    kept, stale = filter_baselined_violations([violation], baseline, tmp_path)
    assert kept == []
    assert stale == []


def test_advisory_ids_are_unbaselinable():
    """Baselining a deprecation notice would permanently hide the removal
    warning; the literal in baseline.py must cover every advisory ID."""
    from skillsaw.baseline import _UNBASELINABLE_RULE_IDS, build_baseline
    from skillsaw.linter import ADVISORY_RULE_IDS

    assert ADVISORY_RULE_IDS <= _UNBASELINABLE_RULE_IDS

    notice = RuleViolation(
        rule_id="deprecated-rule",
        severity=Severity.WARNING,
        message="Rule 'x' is deprecated since 0.18.0",
    )
    baseline = build_baseline([notice], Path("/tmp"), "0.18.0")
    assert baseline.violations == []


def test_baked_advisory_baseline_entry_does_not_suppress(tmp_path):
    """An existing baseline may already contain an advisory entry; matching
    one must not suppress the notice, or the removal warning stays hidden
    until the baseline is regenerated."""
    notice = RuleViolation(
        rule_id="deprecated-rule",
        severity=Severity.WARNING,
        message="Rule 'x' is deprecated since 0.18.0",
    )
    baked = BaselineFile(
        version="1",
        generated_by="skillsaw 0.18.0",
        generated_at="2026-01-01T00:00:00+00:00",
        violations=[
            BaselineEntry(
                fingerprint=fingerprint_violation(notice, tmp_path),
                rule_id="deprecated-rule",
                file_path=None,
                line=None,
                message=notice.message,
                severity="warning",
            )
        ],
        root_path=tmp_path,
    )
    kept, _stale = filter_baselined_violations([notice], baked, tmp_path)
    assert kept == [notice]


def test_custom_rule_cannot_claim_legacy_alias(plugin_repo):
    rule_file = plugin_repo / "lint_rule.py"
    rule_file.write_text(
        "from skillsaw.rule import Rule, Severity\n\n\n"
        "class SquatterRule(Rule):\n"
        "    @property\n"
        "    def rule_id(self):\n"
        '        return "plugin-readme"\n\n'
        "    @property\n"
        "    def description(self):\n"
        '        return "claims a legacy alias"\n\n'
        "    def default_severity(self):\n"
        "        return Severity.ERROR\n\n"
        "    def check(self, context):\n"
        '        return [self.violation("squatted")]\n'
    )
    config = LinterConfig.default()
    config.custom_rules = ["lint_rule.py"]
    config.config_dir = plugin_repo
    context = RepositoryContext(plugin_repo)
    linter = Linter(context, config=config, no_plugins=True)
    results = linter.run()
    # The custom rule is skipped, so its violation never appears — and
    # "plugin-readme" still means the builtin claude-plugin-readme wherever
    # the name is used.
    assert not any(v.message == "squatted" for v in results)
    warnings = [v for v in results if v.rule_id == "plugin-load-error"]
    assert len(warnings) == 1
    assert warnings[0].severity == Severity.WARNING
    assert "legacy alias" in warnings[0].message


def test_custom_rule_cannot_claim_advisory_id(plugin_repo):
    """The advisory half of the custom-rule reservation: findings reported
    under an advisory ID are exempt from the exit code, so a custom rule
    claiming one would report failures that never fail CI."""
    rule_file = plugin_repo / "lint_rule.py"
    rule_file.write_text(
        "from skillsaw.rule import Rule, Severity\n\n\n"
        "class SquatterRule(Rule):\n"
        "    @property\n"
        "    def rule_id(self):\n"
        '        return "deprecated-rule"\n\n'
        "    @property\n"
        "    def description(self):\n"
        '        return "claims an advisory ID"\n\n'
        "    def default_severity(self):\n"
        "        return Severity.ERROR\n\n"
        "    def check(self, context):\n"
        '        return [self.violation("squatted")]\n'
    )
    config = LinterConfig.default()
    config.custom_rules = ["lint_rule.py"]
    config.config_dir = plugin_repo
    context = RepositoryContext(plugin_repo)
    linter = Linter(context, config=config, no_plugins=True)
    results = linter.run()
    assert "deprecated-rule" not in {r.rule_id for r in linter.rules}
    assert not any(v.message == "squatted" for v in results)
    warnings = [v for v in results if v.rule_id == "plugin-load-error"]
    assert len(warnings) == 1
    assert warnings[0].severity == Severity.WARNING
    assert "reserved" in warnings[0].message


# ── Deprecation ─────────────────────────────────────────────────


def test_deprecated_rules_are_marked():
    for rule_id in (
        "content-critical-position",
        "content-actionability-score",
        "skill-frontmatter",
    ):
        assert BUILTIN_RULE_REGISTRY[rule_id].deprecated == "0.18.0", rule_id
    assert BUILTIN_RULE_REGISTRY["skill-frontmatter"].replaced_by == "agentskill-valid"


def test_deprecated_rules_left_out_of_generated_defaults():
    defaults = LinterConfig.default().rules
    for rule_id, cls in BUILTIN_RULE_REGISTRY.items():
        if cls.deprecated is not None:
            assert rule_id not in defaults, rule_id


def test_deprecated_rule_does_not_run_by_default(plugin_repo):
    context = RepositoryContext(plugin_repo)
    linter = Linter(context, no_plugins=True)
    loaded = {r.rule_id for r in linter.rules}
    assert "skill-frontmatter" not in loaded
    assert "content-critical-position" not in loaded


def test_deprecated_rule_runs_when_explicitly_enabled(plugin_repo):
    config = LinterConfig.default()
    config.rules["skill-frontmatter"] = {"enabled": True}
    context = RepositoryContext(plugin_repo)
    linter = Linter(context, config=config, no_plugins=True)
    assert "skill-frontmatter" in {r.rule_id for r in linter.rules}
    results = linter.run()
    deprecation = [v for v in results if v.rule_id == "deprecated-rule"]
    assert len(deprecation) == 1
    assert deprecation[0].severity == Severity.WARNING
    assert "skill-frontmatter" in deprecation[0].message
    assert "removed in a future release" in deprecation[0].message
    assert "agentskill-valid" in deprecation[0].message


def test_deprecated_rule_config_mention_warns_but_does_not_run(plugin_repo):
    config = LinterConfig.default()
    config.rules["content-critical-position"] = {"severity": "warning"}
    context = RepositoryContext(plugin_repo)
    linter = Linter(context, config=config, no_plugins=True)
    assert "content-critical-position" not in {r.rule_id for r in linter.rules}
    results = linter.run()
    deprecation = [v for v in results if v.rule_id == "deprecated-rule"]
    assert len(deprecation) == 1
    assert "no longer runs" in deprecation[0].message


def test_deprecated_rule_runs_via_rule_flag(plugin_repo):
    context = RepositoryContext(plugin_repo)
    linter = Linter(context, rule_ids={"content-critical-position"}, no_plugins=True)
    assert {r.rule_id for r in linter.rules} == {"content-critical-position"}
    results = linter.run()
    deprecation = [v for v in results if v.rule_id == "deprecated-rule"]
    assert len(deprecation) == 1


def test_enabled_reason_mentions_deprecation(plugin_repo):
    config = LinterConfig.default()
    context = RepositoryContext(plugin_repo)
    enabled, reason = config.rule_enabled_reason(
        "content-critical-position", context, deprecated="0.18.0"
    )
    assert enabled is False
    assert "deprecated since 0.18.0" in reason


# ── Baseline aliases (a rule split out of another) ───────────────


def copy_fixture(name, tmp_path):
    destination = tmp_path / name.replace("/", "_")
    shutil.copytree(Path(__file__).parent / "fixtures" / name, destination)
    return destination


def test_baseline_aliases_resolve_nothing_but_baselines():
    """`baseline_aliases` is not an alias: the split rule is named,
    configured and suppressed by its own ID, and `hooks-json-valid` still
    resolves to the rule it was renamed to."""
    assert rule_baseline_aliases("codex-hooks-valid") == ("hooks-json-valid",)
    assert rule_aliases("codex-hooks-valid") == ()
    assert RULE_ALIASES["hooks-json-valid"] == "claude-hooks-valid"
    assert canonical_rule_id("hooks-json-valid") == "claude-hooks-valid"
    assert "codex-hooks-valid" not in RULE_ALIASES.values()


def test_baseline_aliases_never_collide_with_a_rule_id():
    """The same guard `_build_alias_map` applies to `aliases`: a former
    name that is also a live rule ID would silently shadow it."""
    for rule_id, cls in BUILTIN_RULE_REGISTRY.items():
        for former in cls.baseline_aliases:
            assert former != rule_id
            assert former not in BUILTIN_RULE_REGISTRY, (rule_id, former)


def test_a_pre_split_baseline_still_suppresses_a_codex_finding(tmp_path):
    """`codex-hooks-valid` was split out of `hooks-json-valid`, so a
    baseline written before the split recorded this finding under the old
    name. Upgrading must not resurface it."""
    repo = copy_fixture("codex/hooks-pre-split", tmp_path)

    assert run_cli(["baseline", str(repo)]).returncode == 0
    baseline_path = repo / ".skillsaw-baseline.json"
    recorded = json.loads(baseline_path.read_text())
    assert [e["rule_id"] for e in recorded["violations"]] == ["codex-hooks-valid"]

    # Rewrite it the way a pre-split run would have: the fingerprint hashes
    # the rule ID, so the name and the hash both have to move.
    violation = RuleViolation(
        rule_id="codex-hooks-valid",
        severity=Severity.ERROR,
        message=recorded["violations"][0]["message"],
        file_path=repo / "hooks" / "hooks.json",
    )
    recorded["violations"][0]["rule_id"] = "hooks-json-valid"
    recorded["violations"][0]["fingerprint"] = fingerprint_violation(
        violation, repo, _rule_id="hooks-json-valid"
    )
    baseline_path.write_text(json.dumps(recorded, indent=2) + "\n")

    result = run_cli(["lint", "--format", "json", str(repo)])
    found = [
        v for v in json.loads(result.stdout)["violations"] if v["rule_id"] == "codex-hooks-valid"
    ]
    assert found == [], found


def test_the_pre_split_baseline_test_is_not_vacuous(tmp_path):
    """Without the baseline the same lint reports the finding."""
    repo = copy_fixture("codex/hooks-pre-split", tmp_path)
    result = run_cli(["lint", "--format", "json", str(repo)])
    found = [
        v for v in json.loads(result.stdout)["violations"] if v["rule_id"] == "codex-hooks-valid"
    ]
    assert [v["message"] for v in found] == [
        "Hook PostToolUse[0] 'matcher' must be a string, got list"
    ]


#: What ``hooks-json-valid`` printed before 0.20.0 split it by host, for the
#: two files in the fixture. A hooks file is JSON and carries no line
#: numbers, so its baseline fingerprint hashes the message text — which makes
#: the wording, not the rule name, what decides whether an old entry still
#: matches. The first survived the split word-for-word; the second did not.
_PRE_SPLIT_MESSAGES = {
    ".codex/hooks.json": "'hooks' must be a JSON object",
    "hooks/hooks.json": "Event 'PostToolUse[0].matcher' must be a string",
}


def _pre_split_baseline(repo: Path) -> str:
    """A baseline as ``hooks-json-valid`` would have written it on 0.19.x."""
    entries = []
    for relative, message in _PRE_SPLIT_MESSAGES.items():
        violation = RuleViolation(
            rule_id="hooks-json-valid",
            severity=Severity.ERROR,
            message=message,
            file_path=repo / relative,
        )
        entries.append(
            {
                "fingerprint": fingerprint_violation(violation, repo, _rule_id="hooks-json-valid"),
                "rule_id": "hooks-json-valid",
                "file_path": relative,
                "line": None,
                "message": message,
                "severity": "error",
            }
        )
    return json.dumps(
        {
            "version": "1",
            "generated_by": "skillsaw 0.19.2",
            "generated_at": "2026-08-01T00:00:00+00:00",
            "violations": entries,
        },
        indent=2,
    )


def test_a_pre_split_baseline_carries_over_only_the_unchanged_messages(tmp_path):
    """The alias carries an entry across the rename; the message decides
    whether it still matches.

    0.20.0 rewrote most of these findings, and a rewritten one comes back on
    upgrade however the baseline names the rule — worth stating plainly,
    because the alias reads like a promise that nothing resurfaces.
    """
    repo = copy_fixture("codex/hooks-pre-split-messages", tmp_path)
    (repo / ".skillsaw-baseline.json").write_text(_pre_split_baseline(repo))

    result = run_cli(["lint", "--format", "json", str(repo)])
    found = [
        v for v in json.loads(result.stdout)["violations"] if v["rule_id"] == "codex-hooks-valid"
    ]

    # The kept wording matches, so the old entry still suppresses it; the
    # rewritten one no longer hashes to anything the baseline recorded.
    assert [(v["file_path"], v["message"]) for v in found] == [
        ("hooks/hooks.json", "Hook PostToolUse[0] 'matcher' must be a string, got list")
    ]


def test_the_message_carryover_test_is_not_vacuous(tmp_path):
    """Both findings are there to begin with, and the fixture's project file
    really does produce the message that survived the split."""
    repo = copy_fixture("codex/hooks-pre-split-messages", tmp_path)

    result = run_cli(["lint", "--format", "json", str(repo)])
    found = {
        v["file_path"]: v["message"]
        for v in json.loads(result.stdout)["violations"]
        if v["rule_id"] == "codex-hooks-valid"
    }

    assert found == {
        ".codex/hooks.json": "'hooks' must be a JSON object",
        "hooks/hooks.json": "Hook PostToolUse[0] 'matcher' must be a string, got list",
    }
    assert found[".codex/hooks.json"] == _PRE_SPLIT_MESSAGES[".codex/hooks.json"]
    assert found["hooks/hooks.json"] != _PRE_SPLIT_MESSAGES["hooks/hooks.json"]
