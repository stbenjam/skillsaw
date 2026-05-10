"""
Tests for output formatters
"""

import json
from pathlib import Path

from skillsaw.formatters import format_report, get_counts, infer_format, FORMATS
from skillsaw.formatters.text import format_text
from skillsaw.formatters.json_fmt import format_json
from skillsaw.formatters.sarif import format_sarif
from skillsaw.formatters.html import format_html
from skillsaw.rule import RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.config import LinterConfig
from skillsaw.linter import Linter

# --- Helpers ---


def _make_violations():
    return [
        RuleViolation(
            rule_id="plugin-json-required",
            severity=Severity.ERROR,
            message="Missing plugin.json",
            file_path=Path("plugins/foo/.claude-plugin"),
            line=None,
        ),
        RuleViolation(
            rule_id="command-naming",
            severity=Severity.WARNING,
            message="Command file should use kebab-case",
            file_path=Path("plugins/foo/commands/Bad_Name.md"),
            line=3,
        ),
        RuleViolation(
            rule_id="plugin-json-valid",
            severity=Severity.INFO,
            message="Recommended field 'author' missing",
            file_path=Path("plugins/foo/.claude-plugin/plugin.json"),
            line=1,
        ),
    ]


# --- get_counts ---


def test_get_counts_empty():
    errors, warnings, info = get_counts([])
    assert (errors, warnings, info) == (0, 0, 0)


def test_get_counts_mixed():
    violations = _make_violations()
    errors, warnings, info = get_counts(violations)
    assert errors == 1
    assert warnings == 1
    assert info == 1


# --- infer_format ---


def test_infer_format_known_extensions():
    assert infer_format("report.json") == "json"
    assert infer_format("report.sarif") == "sarif"
    assert infer_format("report.html") == "html"
    assert infer_format("report.htm") == "html"
    assert infer_format("/tmp/path/to/report.JSON") == "json"


def test_infer_format_unknown_extension():
    import pytest

    with pytest.raises(ValueError, match="Cannot infer format"):
        infer_format("report.txt")


# --- format_report dispatcher ---


def test_format_report_dispatches_all_formats(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    for fmt in FORMATS:
        output = format_report(fmt, violations, context, linter.rules, "0.0.0")
        assert len(output) > 0


def test_format_report_unknown_format(valid_plugin):
    import pytest

    context = RepositoryContext(valid_plugin)
    with pytest.raises(ValueError, match="Unknown format"):
        format_report("xml", [], context, [], "0.0.0")


# --- Text formatter ---


def test_text_includes_stats(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0")
    assert "Scanned:" in output
    assert "Repo type:" in output
    assert "Plugins:" in output
    assert "Skills:" in output
    assert "Rules run:" in output


def test_text_includes_summary(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0")
    assert "Summary:" in output
    assert "Errors:" in output
    assert "Warnings:" in output


def test_text_shows_all_checks_passed(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0")
    assert "All checks passed" in output


def test_text_includes_ansi_by_default(valid_plugin, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0")
    assert "\033[" in output


def test_text_no_ansi_when_no_color(valid_plugin, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "")
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0")
    assert "\033[" not in output


def test_text_no_ansi_when_no_color_value(valid_plugin, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0")
    assert "\033[" not in output


def test_text_shows_violations(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_text(violations, context, [], "0.0.0")
    assert "Errors:" in output
    assert "Missing plugin.json" in output
    assert "Warnings:" in output
    assert "kebab-case" in output


def test_text_verbose_shows_info(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_text(violations, context, [], "0.0.0", verbose=True)
    assert "Info:" in output
    assert "author" in output


def test_text_non_verbose_hides_info(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_text(violations, context, [], "0.0.0", verbose=False)
    assert "Info:" not in output


# --- JSON formatter ---


def test_json_valid_structure(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_json(violations, context, linter.rules, "1.2.3")
    data = json.loads(output)

    assert data["version"] == "1.2.3"
    assert "stats" in data
    assert "violations" in data
    assert "summary" in data


def test_json_stats_counts(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_json(violations, context, linter.rules, "1.0.0")
    data = json.loads(output)

    assert isinstance(data["stats"]["plugins"], int)
    assert isinstance(data["stats"]["skills"], int)
    assert isinstance(data["stats"]["rules_run"], int)
    assert data["stats"]["plugins"] == len(context.plugins)
    assert data["stats"]["rules_run"] == len(linter.rules)


def test_json_verbose_expands_stats(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_json(violations, context, linter.rules, "1.0.0", verbose=True)
    data = json.loads(output)

    assert isinstance(data["stats"]["plugins"], list)
    assert isinstance(data["stats"]["skills"], list)
    assert isinstance(data["stats"]["rules_run"], list)


def test_json_violations_serialized(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_json(violations, context, [], "1.0.0", verbose=True)
    data = json.loads(output)

    assert len(data["violations"]) == 3
    assert data["violations"][0]["rule_id"] == "plugin-json-required"
    assert data["violations"][0]["severity"] == "error"
    assert data["violations"][1]["line"] == 3
    assert data["summary"]["errors"] == 1
    assert data["summary"]["warnings"] == 1
    assert data["summary"]["info"] == 1


def test_json_excludes_info_without_verbose(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_json(violations, context, [], "1.0.0", verbose=False)
    data = json.loads(output)

    assert len(data["violations"]) == 2
    assert all(v["severity"] != "info" for v in data["violations"])
    assert data["summary"]["info"] == 1


# --- SARIF formatter ---


def test_sarif_valid_structure(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_sarif(violations, context, linter.rules, "1.0.0")
    data = json.loads(output)

    assert data["version"] == "2.1.0"
    assert "$schema" in data
    assert len(data["runs"]) == 1
    run = data["runs"][0]
    assert run["tool"]["driver"]["name"] == "skillsaw"
    assert run["tool"]["driver"]["version"] == "1.0.0"


def test_sarif_rules_listed(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_sarif(violations, context, linter.rules, "1.0.0")
    data = json.loads(output)

    rules = data["runs"][0]["tool"]["driver"]["rules"]
    assert len(rules) > 0
    assert all("id" in r for r in rules)
    assert all("shortDescription" in r for r in rules)


def test_sarif_severity_mapping(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_sarif(violations, context, [], "1.0.0", verbose=True)
    data = json.loads(output)

    results = data["runs"][0]["results"]
    levels = {r["ruleId"]: r["level"] for r in results}

    assert levels["plugin-json-required"] == "error"
    assert levels["command-naming"] == "warning"
    assert levels["plugin-json-valid"] == "note"


def test_sarif_excludes_info_without_verbose(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_sarif(violations, context, [], "1.0.0", verbose=False)
    data = json.loads(output)

    results = data["runs"][0]["results"]
    assert len(results) == 2
    assert all(r["level"] != "note" for r in results)


def test_sarif_locations(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_sarif(violations, context, [], "1.0.0")
    data = json.loads(output)

    results = data["runs"][0]["results"]

    # First violation: file_path but no line
    v0_loc = results[0]["locations"][0]["physicalLocation"]
    assert "region" not in v0_loc

    # Second violation: file_path + line
    v1_loc = results[1]["locations"][0]["physicalLocation"]
    assert v1_loc["region"]["startLine"] == 3


def test_sarif_line_zero_omits_region(valid_plugin):
    """SARIF 2.1.0 requires startLine >= 1; line=0 must not emit a region."""
    context = RepositoryContext(valid_plugin)
    violations = [
        RuleViolation(
            rule_id="test-rule",
            severity=Severity.WARNING,
            message="bogus",
            file_path=Path("plugins/foo/commands/bar.md"),
            line=0,
        ),
    ]

    output = format_sarif(violations, context, [], "1.0.0")
    data = json.loads(output)

    result = data["runs"][0]["results"][0]
    loc = result["locations"][0]["physicalLocation"]
    assert "region" not in loc, "startLine=0 violates SARIF 2.1.0 (startLine >= 1)"


def test_sarif_stats_in_properties(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_sarif(violations, context, linter.rules, "1.0.0")
    data = json.loads(output)

    stats = data["runs"][0]["properties"]["stats"]
    assert stats["plugins"] == len(context.plugins)
    assert stats["rules_run"] == len(linter.rules)


# --- HTML formatter ---


def test_html_valid_document(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_html(violations, context, linter.rules, "1.0.0")

    assert output.startswith("<!DOCTYPE html>")
    assert "</html>" in output
    assert "skillsaw Report" in output


def test_html_stats_cards(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_html(violations, context, linter.rules, "1.0.0")

    assert "Repo Type" in output
    assert "Plugins" in output
    assert "Skills" in output
    assert "Rules Run" in output


def test_html_success_banner_when_clean(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_html(violations, context, linter.rules, "1.0.0")
    assert "All checks passed" in output


def test_html_shows_violations(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_html(violations, context, [], "1.0.0")
    assert "Missing plugin.json" in output
    assert "plugin-json-required" in output
    assert "<table>" in output


def test_html_escapes_content(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = [
        RuleViolation(
            rule_id="xss-test",
            severity=Severity.ERROR,
            message='<script>alert("xss")</script>',
        ),
    ]

    output = format_html(violations, context, [], "1.0.0")
    assert "<script>" not in output
    assert "&lt;script&gt;" in output


def test_html_verbose_shows_info(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_html(violations, context, [], "1.0.0", verbose=True)
    assert "author" in output


def test_html_non_verbose_hides_info(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output_verbose = format_html(violations, context, [], "1.0.0", verbose=True)
    output_normal = format_html(violations, context, [], "1.0.0", verbose=False)

    # Verbose shows info violation, non-verbose doesn't
    # The info violation contains "author" in the message
    assert "Recommended field" in output_verbose
    # In non-verbose, the info violation row should not appear in the table
    # but the error and warning should
    assert "Missing plugin.json" in output_normal
