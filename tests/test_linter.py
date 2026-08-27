"""
Tests for main linter functionality
"""

from pathlib import Path

from skillsaw.linter import Linter
from skillsaw.context import RepositoryContext
from skillsaw.config import LinterConfig
from skillsaw.formatters import get_counts


def test_linter_passes_valid_plugin(valid_plugin):
    """Test that linter passes valid plugin"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)

    violations = linter.run()
    errors, warnings, info = get_counts(violations)

    assert errors == 0
    assert warnings == 0


def test_linter_passes_marketplace(marketplace_repo):
    """Test that linter passes valid marketplace"""
    context = RepositoryContext(marketplace_repo)
    config = LinterConfig.default()
    linter = Linter(context, config)

    violations = linter.run()
    errors, warnings, info = get_counts(violations)

    # Should have no errors (warnings are ok - e.g. missing README)
    assert errors == 0


def test_linter_detects_errors(temp_dir):
    """Test that linter detects errors in invalid plugin"""
    # Create a minimal plugin structure with missing plugin.json
    plugin_dir = temp_dir / "bad-plugin"
    plugin_dir.mkdir()

    # Create .claude-plugin dir but no plugin.json
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    context = RepositoryContext(plugin_dir)
    config = LinterConfig.default()

    # Enable claude-plugin-json-required
    config.rules["claude-plugin-json-required"] = {"enabled": True, "severity": "error"}

    linter = Linter(context, config)
    violations = linter.run()
    errors, warnings, info = get_counts(violations)

    # Should detect missing plugin.json as error
    assert errors > 0


def test_linter_respects_disabled_rules(valid_plugin):
    """Test that disabled rules are not checked"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()

    # Disable all rules
    for rule_id in config.rules:
        config.rules[rule_id]["enabled"] = False

    linter = Linter(context, config, no_plugins=True)

    # Should have no rules loaded
    assert len(linter.rules) == 0


def test_linter_passes_rule_config(valid_plugin):
    """Test that per-rule config from .skillsaw.yaml reaches rule instances"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()

    # Override recommended-fields for claude-plugin-json-valid
    config.rules["claude-plugin-json-valid"]["recommended-fields"] = ["description"]

    linter = Linter(context, config)

    # Find the claude-plugin-json-valid rule and verify it got the config
    pjv_rules = [r for r in linter.rules if r.rule_id == "claude-plugin-json-valid"]
    assert len(pjv_rules) == 1
    assert pjv_rules[0].config.get("recommended-fields") == ["description"]


def test_linter_warns_on_unknown_rule_id(valid_plugin):
    """Test that unknown rule IDs in config produce warnings"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["nonexistent-rule"] = {"enabled": True, "severity": "error"}

    linter = Linter(context, config)
    violations = linter.run()

    unknown_warnings = [
        v for v in violations if v.rule_id == "invalid-config" and "nonexistent-rule" in v.message
    ]
    assert len(unknown_warnings) == 1
    assert unknown_warnings[0].severity.value == "warning"


def test_linter_warns_on_multiple_unknown_rule_ids(valid_plugin):
    """Test that each unknown rule ID produces its own warning"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["fake-rule-one"] = {"enabled": True}
    config.rules["fake-rule-two"] = {"enabled": False}

    linter = Linter(context, config)
    violations = linter.run()

    unknown_warnings = [v for v in violations if v.rule_id == "invalid-config"]
    assert len(unknown_warnings) == 2


def test_linter_no_warning_for_known_rule_ids(valid_plugin):
    """Test that valid rule IDs do not trigger unknown-rule warnings"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()

    linter = Linter(context, config)
    violations = linter.run()

    unknown_warnings = [v for v in violations if v.rule_id == "invalid-config"]
    assert len(unknown_warnings) == 0


def test_per_rule_excludes_skips_matching_file(temp_dir):
    """Test that per-rule excludes skip violations from matching files"""
    # Create a CLAUDE.md with weak language that would normally trigger a violation
    legacy_dir = temp_dir / "skills" / "legacy"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "CLAUDE.md").write_text("Try to handle errors gracefully if possible.\n")

    context = RepositoryContext(temp_dir)
    config = LinterConfig.default()
    config.rules["content-weak-language"] = {
        "enabled": True,
        "severity": "warning",
        "exclude": ["skills/legacy/**"],
    }

    linter = Linter(context, config)
    violations = linter.run()

    # Should have no content-weak-language violations for the excluded file
    weak_violations = [v for v in violations if v.rule_id == "content-weak-language"]
    assert len(weak_violations) == 0


def test_per_rule_excludes_still_fires_for_non_matching(temp_dir):
    """Test that per-rule excludes don't suppress non-matching files"""
    # Create two CLAUDE.md files: one in excluded path, one not
    legacy_dir = temp_dir / "skills" / "legacy"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "CLAUDE.md").write_text("Try to handle errors gracefully if possible.\n")

    (temp_dir / "CLAUDE.md").write_text("Try to handle errors gracefully if possible.\n")

    context = RepositoryContext(temp_dir)
    config = LinterConfig.default()
    config.rules["content-weak-language"] = {
        "enabled": True,
        "severity": "warning",
        "exclude": ["skills/legacy/**"],
    }

    linter = Linter(context, config)
    violations = linter.run()

    # Should still find violations in the non-excluded file
    weak_violations = [v for v in violations if v.rule_id == "content-weak-language"]
    assert len(weak_violations) >= 1
    # All violations should be from the root CLAUDE.md, not the excluded one
    for v in weak_violations:
        assert "legacy" not in str(v.file_path)


def test_per_rule_excludes_no_effect_without_patterns(temp_dir):
    """Test that rules without excludes are not affected"""
    (temp_dir / "CLAUDE.md").write_text("Try to handle errors gracefully if possible.\n")

    context = RepositoryContext(temp_dir)
    config = LinterConfig.default()
    config.rules["content-weak-language"] = {
        "enabled": True,
        "severity": "warning",
    }

    linter = Linter(context, config)
    violations = linter.run()

    weak_violations = [v for v in violations if v.rule_id == "content-weak-language"]
    assert len(weak_violations) >= 1


def test_self_lint():
    """Skillsaw's own .claude/ directory should pass linting with no errors"""
    repo_root = Path(__file__).parent.parent
    context = RepositoryContext(repo_root)
    config_path = repo_root / ".skillsaw.yaml"
    config = LinterConfig.from_file(config_path) if config_path.exists() else LinterConfig.default()
    linter = Linter(context, config)

    # Exclude intentional test fixtures (PR #29: code scanning test)
    test_fixtures = {"Bad_Skill"}
    violations = linter.run()
    errors = [
        v
        for v in violations
        if v.severity.value == "error"
        and not any(part in str(v.file_path) for part in test_fixtures)
    ]

    assert len(errors) == 0, f"Self-lint found errors: {errors}"


class _CrashingRule:
    """Stand-in rule whose check() always raises."""

    rule_id = "crashing-rule"
    description = "always crashes"
    supports_autofix = False

    def check(self, context):
        raise RuntimeError("boom")


def test_rule_crash_produces_error_violation(valid_plugin, capsys):
    """A rule that raises during check() surfaces as an ERROR violation."""
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, LinterConfig.default())
    linter.rules = [_CrashingRule()]

    violations = linter.run()

    crashes = [v for v in violations if v.rule_id == "rule-execution-error"]
    assert len(crashes) == 1
    assert crashes[0].severity.value == "error"
    assert "crashing-rule" in crashes[0].message
    assert "RuntimeError" in crashes[0].message
    assert "boom" in crashes[0].message
    # Still printed to stderr for visibility
    assert "Error running rule crashing-rule" in capsys.readouterr().err

    errors, _, _ = get_counts(violations)
    assert errors >= 1


def test_rule_crash_in_fix_produces_error_violation(valid_plugin):
    """A rule that raises during fix()'s check pass surfaces as an ERROR violation."""
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, LinterConfig.default())
    linter.rules = [_CrashingRule()]

    violations, fixes = linter.fix()

    crashes = [v for v in violations if v.rule_id == "rule-execution-error"]
    assert len(crashes) == 1
    assert crashes[0].severity.value == "error"
    assert fixes == []


class _CrashingFixRule:
    """Stand-in rule whose check() succeeds but fix() always raises."""

    rule_id = "crashing-fix-rule"
    description = "fix always crashes"
    supports_autofix = True

    def check(self, context):
        from skillsaw.rule import RuleViolation, Severity

        return [
            RuleViolation(
                rule_id="crashing-fix-rule",
                severity=Severity.WARNING,
                message="needs fixing",
            )
        ]

    def fix(self, context, violations):
        raise RuntimeError("fix boom")


def test_rule_crash_during_autofix_produces_error_violation(valid_plugin):
    """A rule that raises during fix()'s autofix pass surfaces as an ERROR violation."""
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, LinterConfig.default())
    linter.rules = [_CrashingFixRule()]

    violations, fixes = linter.fix()

    crashes = [v for v in violations if v.rule_id == "rule-execution-error"]
    assert len(crashes) == 1
    assert crashes[0].severity.value == "error"
    assert "during fix" in crashes[0].message
    assert "fix boom" in crashes[0].message
    # The unfixed violations are still reported alongside the crash
    assert any(v.rule_id == "crashing-fix-rule" for v in violations)
    assert fixes == []


def test_run_reports_progress_per_rule(valid_plugin):
    """run(progress=cb) must invoke cb once per enabled rule, in order."""
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, LinterConfig.default())

    calls = []
    linter.run(progress=lambda i, total, rule_id: calls.append((i, total, rule_id)))

    total = len(linter.rules)
    assert len(calls) == total
    assert calls[0] == (1, total, linter.rules[0].rule_id)
    assert calls[-1] == (total, total, linter.rules[-1].rule_id)
    assert [c[0] for c in calls] == list(range(1, total + 1))


def test_fix_reports_progress_per_rule(valid_plugin):
    """fix(progress=cb) must invoke cb once per enabled rule."""
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, LinterConfig.default())

    calls = []
    linter.fix(progress=lambda i, total, rule_id: calls.append((i, total, rule_id)))
    assert len(calls) == len(linter.rules)


def _option_warnings(violations, rule_id=None):
    return [
        v
        for v in violations
        if v.rule_id == "invalid-config"
        and "option" in v.message.lower()
        and (rule_id is None or f"'{rule_id}'" in v.message)
    ]


def test_unknown_option_warns_with_suggestion(valid_plugin):
    """A typo'd option key warns and suggests the nearest valid key."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["agentskill-description"]["severty"] = "error"

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "agentskill-description")
    assert len(warnings) == 1
    assert "Unknown option 'severty'" in warnings[0].message
    assert "did you mean 'severity'" in warnings[0].message
    assert warnings[0].severity.value == "warning"


def test_wrong_separator_option_suggests_declared_key(valid_plugin):
    """max-length suggests the schema's max_length (hyphen/underscore mixups)."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["agentskill-description"]["max-length"] = 100

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "agentskill-description")
    assert len(warnings) == 1
    assert "did you mean 'max_length'" in warnings[0].message


def test_unknown_option_without_near_match_has_no_suggestion(valid_plugin):
    """A key with no close match warns without a did-you-mean clause."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["agentskill-description"]["zzqx-bogus-param"] = 42

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "agentskill-description")
    assert len(warnings) == 1
    assert "did you mean" not in warnings[0].message
    assert "skillsaw explain agentskill-description" in warnings[0].message


def test_suggestion_cutoff_matches_at_point_six(valid_plugin):
    """'length' (ratio 0.75 vs max_length) must still get a suggestion."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["agentskill-description"]["length"] = 100

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "agentskill-description")
    assert len(warnings) == 1
    assert "did you mean 'max_length'" in warnings[0].message


def test_option_validation_is_enablement_independent(valid_plugin):
    """Typos warn even on disabled, auto-inactive, and deprecated rules."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    # Disabled builtin.
    config.rules["content-weak-language"] = {"enabled": False, "severty": "error"}
    # Auto rule whose repo types don't match a single-plugin fixture.
    config.rules["codex-plugin-json-valid"]["requird-fields"] = []
    # Deprecated rule: absent from default().rules, assign a fresh dict.
    config.rules["content-critical-position"] = {"enabled": False, "windw": 10}

    violations = Linter(context, config).run()
    assert len(_option_warnings(violations, "content-weak-language")) == 1
    assert len(_option_warnings(violations, "codex-plugin-json-valid")) == 1
    assert len(_option_warnings(violations, "content-critical-position")) == 1


def test_typo_on_opt_in_rule_warns_and_still_enables_it(valid_plugin):
    """An unknown override activates a default-disabled rule as configuration."""
    config = LinterConfig.default()
    config.rules["content-missing-stop-condition"] = {"extra-loop-pattrns": []}

    linter = Linter(RepositoryContext(valid_plugin), config)
    violations = linter.run()
    warnings = _option_warnings(violations, "content-missing-stop-condition")

    assert "content-missing-stop-condition" in {rule.rule_id for rule in linter.rules}
    assert len(warnings) == 1
    assert "may enable an opt-in rule" in warnings[0].message
    assert "will be ignored" not in warnings[0].message


def test_non_string_option_keys_warn_without_crashing(valid_plugin):
    """YAML keys like `on:` parse to bool; they must warn, not crash."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["content-weak-language"] = {True: "x", 5: "y"}

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "content-weak-language")
    assert len(warnings) == 2
    assert all("option keys must be strings" in w.message for w in warnings)


def test_option_type_mismatches_warn(valid_plugin):
    """Wrong-typed values for declared options warn; the lint still runs."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["content-section-length"] = {"enabled": True, "max-tokens": "five"}
    config.rules["context-budget"] = {"enabled": True, "limits": "nope"}

    violations = Linter(context, config).run()
    section = _option_warnings(violations, "content-section-length")
    assert len(section) == 1
    assert "expects int, got str" in section[0].message
    budget = _option_warnings(violations, "context-budget")
    assert len(budget) == 1
    assert "expects dict, got str" in budget[0].message


def test_bool_rejected_for_int_option(valid_plugin):
    """bool is a subclass of int but must not satisfy an int option."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["content-section-length"] = {"enabled": True, "max-tokens": True}

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "content-section-length")
    assert len(warnings) == 1
    assert "expects int, got bool" in warnings[0].message


def test_null_option_value_warns(valid_plugin):
    """An explicit null bypasses the rule's default — flag it."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["content-section-length"] = {"enabled": True, "max-tokens": None}

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "content-section-length")
    assert len(warnings) == 1
    assert "expects int, got null" in warnings[0].message


def test_int_accepted_for_float_option(valid_plugin):
    """YAML `4` for a float-typed threshold is fine."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["security-encoded-payload"]["entropy-threshold"] = 4

    violations = Linter(context, config).run()
    assert _option_warnings(violations, "security-encoded-payload") == []


def test_dict_option_inner_keys_not_validated(valid_plugin):
    """Validation is non-recursive: unknown inner keys of a dict option pass."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["context-budget"] = {"enabled": True, "limits": {"my-category": 5}}

    violations = Linter(context, config).run()
    assert _option_warnings(violations, "context-budget") == []


def test_universal_keys_never_warn(valid_plugin):
    """enabled/severity/exclude are accepted on every rule."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["content-weak-language"] = {
        "enabled": True,
        "severity": "info",
        "exclude": ["docs/*"],
    }

    violations = Linter(context, config).run()
    assert _option_warnings(violations, "content-weak-language") == []


def test_schema_declared_exclude_is_type_checked(valid_plugin):
    """agentskill-unreferenced-files declares exclude as a list, so a str warns
    via the schema type check; the universal exclude is list-checked too."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["agentskill-unreferenced-files"]["exclude"] = "references/*"

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "agentskill-unreferenced-files")
    assert len(warnings) == 1
    assert "expects list of strings, got str" in warnings[0].message

    config2 = LinterConfig.default()
    config2.rules["agentskill-unreferenced-files"]["exclude"] = ["references/*"]
    violations2 = Linter(RepositoryContext(valid_plugin), config2).run()
    assert _option_warnings(violations2, "agentskill-unreferenced-files") == []


def test_unknown_option_on_empty_schema_builtin_warns(valid_plugin):
    """Builtins with no config_schema accept only universal keys."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["content-weak-language"] = {"enabled": True, "extra-words": ["maybe"]}

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "content-weak-language")
    assert len(warnings) == 1
    assert "Unknown option 'extra-words'" in warnings[0].message


def test_multiple_bad_options_warn_individually(valid_plugin):
    """One warning per bad key."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["agentskill-description"]["severty"] = "error"
    config.rules["agentskill-description"]["zzqx-bogus"] = 1

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "agentskill-description")
    assert len(warnings) == 2
    assert len({warning.fingerprint_discriminator for warning in warnings}) == 2


def test_universal_exclude_must_be_a_list(valid_plugin):
    """A bare-string exclude iterates per character and its lone `*` would
    silently exclude every file — warn on it even without a schema entry."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["content-weak-language"] = {"enabled": True, "exclude": "docs/*"}

    violations = Linter(context, config).run()
    warnings = _option_warnings(violations, "content-weak-language")
    assert len(warnings) == 1
    assert "Option 'exclude'" in warnings[0].message
    assert "expects list of strings, got str" in warnings[0].message


def test_malformed_exclude_cannot_suppress_or_crash_rule(temp_dir):
    """Bad per-rule excludes warn and fail open so the protected rule runs."""
    target = temp_dir / "CLAUDE.md"
    target.write_text("Try to handle errors gracefully if possible.\n")

    for exclude in ("*.md", [123], None):
        config = LinterConfig.default()
        config.rules["content-weak-language"] = {
            "enabled": True,
            "severity": "warning",
            "exclude": exclude,
        }
        violations = Linter(RepositoryContext(temp_dir), config).run()

        warnings = _option_warnings(violations, "content-weak-language")
        assert len(warnings) == 1, exclude
        assert "expects list of strings" in warnings[0].message
        assert any(v.rule_id == "content-weak-language" for v in violations), exclude


def test_config_option_warning_carries_config_path(valid_plugin, temp_dir):
    config_path = temp_dir / ".skillsaw.yaml"
    config_path.write_text(
        'version: "0.19.0"\nrules:\n  agentskill-description:\n    severty: error\n'
    )
    config = LinterConfig.from_file(config_path)

    warnings = _option_warnings(Linter(RepositoryContext(valid_plugin), config).run())
    assert len(warnings) == 1
    assert warnings[0].file_path == config_path.resolve()
    assert warnings[0].file_line == 4


def test_config_warnings_survive_global_exclude_of_config_file(temp_dir):
    """A global exclude matching the config file must not silence
    invalid-config warnings — they point at the config itself, not at a
    lint target the exclude was written to skip."""
    config_path = temp_dir / ".skillsaw.yaml"
    config_path.write_text(
        'version: "0.19.0"\n'
        "exclude:\n"
        '  - "**/*.yaml"\n'
        "rules:\n"
        "  nonexistent-rule:\n"
        "    enabled: true\n"
        "  agentskill-description:\n"
        "    severty: error\n"
    )
    config = LinterConfig.from_file(config_path)

    context = RepositoryContext(temp_dir, exclude_patterns=config.exclude_patterns)
    violations = Linter(context, config).run()

    unknown_rule = [
        v for v in violations if v.rule_id == "invalid-config" and "nonexistent-rule" in v.message
    ]
    assert len(unknown_rule) == 1
    warnings = _option_warnings(violations, "agentskill-description")
    assert len(warnings) == 1
    assert "Unknown option 'severty'" in warnings[0].message


def test_config_warnings_survive_self_referential_rule_exclude(temp_dir):
    """rules: {invalid-config: {exclude: ["*"]}} must not suppress the
    config warnings reported under that synthetic rule ID."""
    config_path = temp_dir / ".skillsaw.yaml"
    config_path.write_text(
        'version: "0.19.0"\n'
        "rules:\n"
        "  invalid-config:\n"
        '    exclude: ["*"]\n'
        "  agentskill-description:\n"
        "    severty: error\n"
    )
    config = LinterConfig.from_file(config_path)

    violations = Linter(RepositoryContext(temp_dir), config).run()

    warnings = _option_warnings(violations, "agentskill-description")
    assert len(warnings) == 1
    assert "Unknown option 'severty'" in warnings[0].message


def test_inline_directive_still_silences_a_config_warning(temp_dir):
    """The deliberate escape hatch: an inline skillsaw-disable-next-line
    comment above the flagged config line suppresses that one warning."""
    config_path = temp_dir / ".skillsaw.yaml"
    config_path.write_text(
        'version: "0.19.0"\n'
        "rules:\n"
        "  agentskill-description:\n"
        "    # skillsaw-disable-next-line invalid-config\n"
        "    severty: error\n"
    )
    config = LinterConfig.from_file(config_path)

    violations = Linter(RepositoryContext(temp_dir), config).run()

    assert _option_warnings(violations, "agentskill-description") == []


def test_blanket_directives_do_not_silence_config_warnings(temp_dir):
    """Only a disable-next-line naming the rule works for invalid-config: a
    region disable at the top of the file, or a bare all-rules next-line,
    is the same blanket the exclude exemption closes."""
    region = temp_dir / ".skillsaw.yaml"
    region.write_text(
        "# skillsaw-disable invalid-config\n"
        'version: "0.19.0"\n'
        "rules:\n"
        "  agentskill-description:\n"
        "    severty: error\n"
    )
    config = LinterConfig.from_file(region)
    violations = Linter(RepositoryContext(temp_dir), config).run()
    assert len(_option_warnings(violations, "agentskill-description")) == 1

    bare = temp_dir / "bare" / ".skillsaw.yaml"
    bare.parent.mkdir()
    bare.write_text(
        'version: "0.19.0"\n'
        "rules:\n"
        "  agentskill-description:\n"
        "    # skillsaw-disable-next-line\n"
        "    severty: error\n"
    )
    config = LinterConfig.from_file(bare)
    violations = Linter(RepositoryContext(temp_dir / "bare"), config).run()
    assert len(_option_warnings(violations, "agentskill-description")) == 1


def test_baseline_absorbs_option_warnings(temp_dir):
    """invalid-config is deliberately baselinable — the documented migration
    path — and the linter's baseline subtraction absorbs it end to end."""
    from skillsaw.baseline import build_baseline

    config_path = temp_dir / ".skillsaw.yaml"
    config_path.write_text(
        'version: "0.19.0"\nrules:\n  agentskill-description:\n    severty: error\n'
    )
    config = LinterConfig.from_file(config_path)

    first = Linter(RepositoryContext(temp_dir), config).run()
    assert len(_option_warnings(first, "agentskill-description")) == 1

    baseline = build_baseline(first, temp_dir, "0.19.0")
    second = Linter(RepositoryContext(temp_dir), config, baseline=baseline).run()
    assert _option_warnings(second, "agentskill-description") == []


def test_fix_filters_config_warnings_like_run(temp_dir):
    """fix() returns config warnings through the same filter pipeline as
    run(): an inline-suppressed warning must not resurface there."""
    config_path = temp_dir / ".skillsaw.yaml"
    config_path.write_text(
        'version: "0.19.0"\n'
        "rules:\n"
        "  agentskill-description:\n"
        "    # skillsaw-disable-next-line invalid-config\n"
        "    severty: error\n"
    )
    config = LinterConfig.from_file(config_path)

    remaining, _fixes = Linter(RepositoryContext(temp_dir), config).fix()
    assert _option_warnings(remaining, "agentskill-description") == []
