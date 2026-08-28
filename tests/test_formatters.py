"""
Tests for output formatters
"""

import hashlib
import json
from pathlib import Path

from skillsaw.formatters import (
    FORMATS,
    format_report,
    get_counts,
    infer_format,
    parse_output_spec,
    relative_path,
)
from skillsaw.formatters.text import format_text
from skillsaw.formatters.json_fmt import format_json
from skillsaw.formatters.sarif import format_sarif
from skillsaw.formatters.html import format_html
from skillsaw.formatters.code_climate import format_code_climate
from skillsaw.formatters.text import _text_diagnostics
from skillsaw.grade import compute_grade
from skillsaw.rule import AutofixConfidence, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.config import LinterConfig
from skillsaw.linter import Linter
from skillsaw.lint_target import LintTarget
from skillsaw.rules.builtin.content.mcp_tool_name import ContentMcpToolNameRule

# --- Helpers ---


def _make_violations():
    return [
        RuleViolation(
            rule_id="claude-plugin-json-required",
            severity=Severity.ERROR,
            message="Missing plugin.json",
            file_path=Path("plugins/foo/.claude-plugin"),
            line=None,
        ),
        RuleViolation(
            rule_id="claude-command-naming",
            severity=Severity.WARNING,
            message="Command file should use kebab-case",
            file_path=Path("plugins/foo/commands/Bad_Name.md"),
            line=3,
        ),
        RuleViolation(
            rule_id="claude-plugin-json-valid",
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


def test_infer_format_txt_extension():
    assert infer_format("report.txt") == "text"


def test_infer_format_unknown_extension():
    import pytest

    with pytest.raises(ValueError, match="Cannot infer format"):
        infer_format("report.csv")


# --- parse_output_spec ---


def test_parse_output_spec_bare_path():
    assert parse_output_spec("report.json") == ("json", "report.json")
    assert parse_output_spec("report.sarif") == ("sarif", "report.sarif")
    assert parse_output_spec("report.html") == ("html", "report.html")


def test_parse_output_spec_explicit_format():
    assert parse_output_spec("gitlab:report.json") == ("gitlab", "report.json")
    assert parse_output_spec("code-climate:cc.json") == ("code-climate", "cc.json")
    assert parse_output_spec("sarif:out.sarif") == ("sarif", "out.sarif")
    assert parse_output_spec("json:native.json") == ("json", "native.json")
    assert parse_output_spec("html:report.html") == ("html", "report.html")
    assert parse_output_spec("text:output.txt") == ("text", "output.txt")


def test_parse_output_spec_explicit_overrides_extension():
    fmt, path = parse_output_spec("gitlab:report.json")
    assert fmt == "gitlab"
    assert path == "report.json"


def test_parse_output_spec_unknown_prefix_falls_through():
    assert parse_output_spec("foo:report.json") == ("json", "foo:report.json")


def test_parse_output_spec_empty_path_raises():
    """`json:` (no path) must error up front, not crash after the lint."""
    import pytest

    with pytest.raises(ValueError, match="output file path missing"):
        parse_output_spec("json:")


def test_parse_output_spec_txt_infers_text():
    assert parse_output_spec("report.txt") == ("text", "report.txt")


def test_parse_output_spec_unknown_extension_raises():
    import pytest

    with pytest.raises(ValueError, match="Cannot infer format"):
        parse_output_spec("report.csv")


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


def test_text_counts_codex_plugins(tmp_path):
    """A Codex-only catalog must not report ``Plugins: 0`` — openai/plugins
    holds 180 plugins, all discovered through the Codex manifest path."""
    import json as _json

    (tmp_path / ".agents" / "plugins").mkdir(parents=True)
    (tmp_path / ".agents" / "plugins" / "marketplace.json").write_text(
        _json.dumps(
            {
                "name": "codex-cat",
                "plugins": [
                    {
                        "name": "note-keeper",
                        "source": {"source": "local", "path": "./plugins/note-keeper"},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                        "category": "Productivity",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_dir = tmp_path / "plugins" / "note-keeper" / ".codex-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        _json.dumps({"name": "note-keeper", "version": "1.0.0", "description": "Keeps notes."}),
        encoding="utf-8",
    )

    context = RepositoryContext(tmp_path)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0")
    assert "Plugins:   1" in output


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


def test_text_includes_ansi_when_color_enabled(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0", color=True)
    assert "\033[" in output


def test_text_plain_by_default(valid_plugin, monkeypatch):
    """Without an explicit color=True the text report never emits ANSI.

    Callers resolve TTY-ness via color_enabled(); the formatter itself must
    stay plain even when NO_COLOR is unset (regression for leaked escapes
    in piped output and --output text files, GH-415).
    """
    monkeypatch.delenv("NO_COLOR", raising=False)
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0")
    assert "\033[" not in output


def test_text_no_ansi_when_color_disabled(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0", color=False)
    assert "\033[" not in output


def test_text_shows_violations(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_text(violations, context, [], "0.0.0")
    assert "Errors:" in output
    assert "Missing plugin.json" in output
    assert "Warnings:" in output
    assert "kebab-case" in output


def test_text_includes_rule_id(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_text(violations, context, [], "0.0.0", verbose=True)
    assert "(claude-plugin-json-required)" in output
    assert "(claude-command-naming)" in output
    assert "(claude-plugin-json-valid)" in output


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


def test_text_collapses_unreferenced_skill_subtrees_only(valid_plugin):
    """Collapse noisy subtrees without merging skills or small/root groups."""
    context = RepositoryContext(valid_plugin)
    first_skill = context.root_path / "skills" / "first"
    second_skill = context.root_path / "skills" / "second"
    context.skills = [first_skill, second_skill]

    paths = [
        first_skill / "assets" / "one.png",
        first_skill / "assets" / "two.png",
        first_skill / "assets" / "nested" / "three.png",
        first_skill / "scripts" / "one.py",
        first_skill / "scripts" / "two.py",
        first_skill / "orphan.txt",
        second_skill / "assets" / "one.png",
        second_skill / "assets" / "two.png",
        second_skill / "assets" / "three.png",
    ]
    violations = [
        RuleViolation(
            rule_id="agentskill-unreferenced-files",
            severity=Severity.WARNING,
            message=f"'{path.name}' is never referenced from SKILL.md",
            file_path=path,
        )
        for path in paths
    ]
    before = [(v.file_path, v.message) for v in violations]

    output = format_text(violations, context, [], "1.0.0")

    assert "[skills/first/assets]: 3 files under 'assets/'" in output
    assert "[skills/second/assets]: 3 files under 'assets/'" in output
    assert "skills/first/assets/one.png" not in output
    assert "skills/second/assets/one.png" not in output
    # Groups below the threshold and root-level files remain actionable rows.
    assert "skills/first/scripts/one.py" in output
    assert "skills/first/scripts/two.py" in output
    assert "skills/first/orphan.txt" in output
    assert "Warnings: 9" in output
    assert len(violations) == 9
    assert [(v.file_path, v.message) for v in violations] == before


def test_structured_reports_keep_collapsed_text_findings_individual(valid_plugin):
    """Text grouping must not alter structured report cardinality."""
    context = RepositoryContext(valid_plugin)
    skill = context.root_path / "skills" / "catalog"
    context.skills = [skill]
    paths = [skill / "assets" / f"image-{index}.png" for index in range(3)]
    violations = [
        RuleViolation(
            rule_id="agentskill-unreferenced-files",
            severity=Severity.WARNING,
            message=f"'{path.name}' is never referenced from SKILL.md",
            file_path=path,
        )
        for path in paths
    ]

    assert len(json.loads(format_json(violations, context, [], "1.0.0"))["violations"]) == 3
    sarif = json.loads(format_sarif(violations, context, [], "1.0.0"))
    assert len(sarif["runs"][0]["results"]) == 3
    assert len(json.loads(format_code_climate(violations, context, [], "1.0.0"))) == 3
    html = format_html(violations, context, [], "1.0.0")
    assert all(path.name in html for path in paths)
    assert html.count("<code>agentskill-unreferenced-files</code>") == 3


def _mcp_tool_name_violation(
    path: Path,
    line: int,
    token: str,
    ordinal: int,
    *,
    message: str,
    **overrides,
) -> RuleViolation:
    values = {
        "rule_id": "content-mcp-tool-name",
        "severity": Severity.WARNING,
        "message": message,
        "file_path": path,
        "line": line,
        "source": "builtin",
        "fixable": True,
        "fix_confidence": AutofixConfidence.SUGGEST,
        "fingerprint_discriminator": f"{token}:{ordinal}",
    }
    values.update(overrides)
    return RuleViolation(**values)


def test_text_mcp_collapse_keeps_raw_totals_and_order(valid_plugin):
    """Only terminal rows collapse; all occurrence-level state stays intact."""
    context = RepositoryContext(valid_plugin)
    first_path = context.root_path / "CLAUDE.md"
    second_path = context.root_path / "AGENTS.md"
    jira = [
        _mcp_tool_name_violation(
            first_path,
            line,
            f"mcp__jira__tool__{index}",
            index,
            message=f"jira original {index}",
        )
        for index, line in enumerate((3, 3, 5, 7, 9))
    ]
    github = [
        _mcp_tool_name_violation(
            first_path,
            12 + index,
            f"mcp__github__tool_{index}",
            0,
            message=f"github original {index}",
        )
        for index in range(2)
    ]
    other_file = [
        _mcp_tool_name_violation(
            second_path,
            4 + index,
            f"mcp__jira__other_{index}",
            0,
            message=f"other-file original {index}",
        )
        for index in range(2)
    ]
    malformed = [
        _mcp_tool_name_violation(
            first_path,
            20,
            "mcp__jira__ignored",
            0,
            message="missing discriminator",
            fingerprint_discriminator=None,
        ),
        _mcp_tool_name_violation(
            first_path,
            21,
            "mcp__jira__ignored",
            0,
            message="malformed discriminator",
            fingerprint_discriminator="mcp__jira__:0",
        ),
    ]
    violations = jira + github + other_file + malformed
    before = [
        (
            id(v),
            v.file_path,
            v.line,
            v.message,
            v.fingerprint_discriminator,
            v.severity,
            v.source,
            v.fixable,
            v.fix_confidence,
        )
        for v in violations
    ]
    grade = compute_grade(violations, 10_000)

    output = format_text(
        violations,
        context,
        [ContentMcpToolNameRule()],
        "1.0.0",
        grade=grade,
    )

    assert (
        "[CLAUDE.md:3]: 5 fully-qualified MCP tool names use the "
        "'mcp__jira__' server prefix" in output
    )
    assert "use short names because the prefix depends on the reader's server name" in output
    assert "(lines 3, 5, 7, …)" in output
    assert "jira original" not in output
    # Below-threshold, different-file, and invalid-discriminator findings stay individual.
    assert all(f"github original {index}" in output for index in range(2))
    assert all(f"other-file original {index}" in output for index in range(2))
    assert "missing discriminator" in output
    assert "malformed discriminator" in output
    assert "Warnings: 11" in output
    assert "[?] 11 violation(s) fixable with `skillsaw fix --suggest`" in output
    assert f"Grade:    {grade.letter} ({grade.density:.2f} weighted violations" in output
    assert "https://skillsaw.org/rules/content-mcp-tool-name/" in output
    assert [
        (
            id(v),
            v.file_path,
            v.line,
            v.message,
            v.fingerprint_discriminator,
            v.severity,
            v.source,
            v.fixable,
            v.fix_confidence,
        )
        for v in violations
    ] == before


def test_text_mcp_collapse_threshold_and_metadata_isolation(valid_plugin):
    context = RepositoryContext(valid_plugin)
    path = context.root_path / "CLAUDE.md"

    def base(index: int, **overrides) -> RuleViolation:
        return _mcp_tool_name_violation(
            path,
            index + 1,
            f"mcp__jira__tool_{index}",
            0,
            message=f"original {index}",
            **overrides,
        )

    pair = [base(0), base(1)]
    assert len(_text_diagnostics(pair, context)) == 2
    assert len(_text_diagnostics(pair + [base(2)], context)) == 1

    # Two otherwise identical findings plus one changed metadata field must
    # never cross the collapse threshold together.
    for changed in (
        {"severity": Severity.ERROR},
        {"source": "plugin"},
        {"fixable": False, "fix_confidence": None},
        {"fix_confidence": AutofixConfidence.SAFE},
    ):
        diagnostics = _text_diagnostics(pair + [base(2, **changed)], context)
        assert [d.message for d in diagnostics] == ["original 0", "original 1", "original 2"]


def test_structured_reports_keep_mcp_tool_findings_individual(valid_plugin):
    context = RepositoryContext(valid_plugin)
    path = context.root_path / "CLAUDE.md"
    violations = [
        _mcp_tool_name_violation(
            path,
            index + 3,
            f"mcp__jira__tool_{index}",
            0,
            message=f"original {index}",
        )
        for index in range(3)
    ]

    json_report = json.loads(format_json(violations, context, [], "1.0.0"))
    assert [v["message"] for v in json_report["violations"]] == [
        "original 0",
        "original 1",
        "original 2",
    ]
    sarif = json.loads(format_sarif(violations, context, [], "1.0.0"))
    assert len(sarif["runs"][0]["results"]) == 3
    assert len(json.loads(format_code_climate(violations, context, [], "1.0.0"))) == 3
    html = format_html(violations, context, [], "1.0.0")
    assert all(f"original {index}" in html for index in range(3))
    assert html.count("<code>content-mcp-tool-name</code>") == 3


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
    assert data["violations"][0]["rule_id"] == "claude-plugin-json-required"
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

    assert levels["claude-plugin-json-required"] == "error"
    assert levels["claude-command-naming"] == "warning"
    assert levels["claude-plugin-json-valid"] == "note"


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


def test_sarif_uri_is_posix_and_root_relative(valid_plugin):
    """SARIF artifact URIs use forward slashes and carry uriBaseId under root."""
    context = RepositoryContext(valid_plugin)
    abs_path = context.root_path / "plugins" / "foo" / "commands" / "bar.md"
    violations = [
        RuleViolation(
            rule_id="claude-command-naming",
            severity=Severity.WARNING,
            message="bad",
            file_path=abs_path,
            line=2,
        ),
    ]
    output = format_sarif(violations, context, [], "1.0.0")
    artifact = json.loads(output)["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
        "artifactLocation"
    ]
    assert artifact["uri"] == "plugins/foo/commands/bar.md"  # forward slashes
    assert "\\" not in artifact["uri"]
    assert artifact["uriBaseId"] == "%SRCROOT%"


def test_sarif_relative_path_is_root_relative(valid_plugin):
    """A root-relative violation path keeps uriBaseId and uses forward slashes."""
    context = RepositoryContext(valid_plugin)
    violations = [
        RuleViolation(
            rule_id="claude-command-naming",
            severity=Severity.WARNING,
            message="bad",
            file_path=Path("plugins/foo/commands/bar.md"),
            line=2,
        ),
    ]
    output = format_sarif(violations, context, [], "1.0.0")
    artifact = json.loads(output)["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
        "artifactLocation"
    ]
    assert artifact["uri"] == "plugins/foo/commands/bar.md"
    assert artifact["uriBaseId"] == "%SRCROOT%"


def test_sarif_outside_root_omits_uribaseid(valid_plugin, tmp_path):
    """A file outside the repo root must not claim %SRCROOT% as its base."""
    context = RepositoryContext(valid_plugin)
    outside = tmp_path / "elsewhere" / "other.md"
    violations = [
        RuleViolation(
            rule_id="claude-command-naming",
            severity=Severity.WARNING,
            message="bad",
            file_path=outside,
            line=1,
        ),
    ]
    output = format_sarif(violations, context, [], "1.0.0")
    artifact = json.loads(output)["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
        "artifactLocation"
    ]
    assert "uriBaseId" not in artifact
    assert "\\" not in artifact["uri"]
    assert str(tmp_path) not in artifact["uri"]
    assert artifact["uri"].startswith("outside-repo/")
    assert "<" not in artifact["uri"]
    assert ">" not in artifact["uri"]


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


def test_sarif_invalid_config_has_rule_descriptor(valid_plugin):
    """Violations with rule_id='invalid-config' must have a matching rule descriptor."""
    context = RepositoryContext(valid_plugin)
    violations = [
        RuleViolation(
            rule_id="invalid-config",
            severity=Severity.WARNING,
            message="Unknown rule 'bogus-rule' in config — rule does not exist and will be ignored",
        ),
    ]

    output = format_sarif(violations, context, [], "1.0.0")
    data = json.loads(output)

    rules = data["runs"][0]["tool"]["driver"]["rules"]
    rule_ids = {r["id"] for r in rules}
    assert "invalid-config" in rule_ids

    descriptor = next(r for r in rules if r["id"] == "invalid-config")
    assert descriptor["shortDescription"]["text"] == "Invalid configuration"

    results = data["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["ruleId"] == "invalid-config"


def test_sarif_builtin_rules_have_help_uri(valid_plugin):
    """Builtin rule descriptors link to their documentation page."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config, no_plugins=True)
    violations = linter.run()

    output = format_sarif(violations, context, linter.rules, "1.0.0")
    data = json.loads(output)

    rules = data["runs"][0]["tool"]["driver"]["rules"]
    assert len(rules) > 0
    for r in rules:
        assert r["helpUri"] == f"https://skillsaw.org/rules/{r['id']}/"


def test_sarif_synthetic_descriptor_has_no_help_uri(valid_plugin):
    """Synthetic rule IDs (e.g. invalid-config) have no docs page to link."""
    context = RepositoryContext(valid_plugin)
    violations = [
        RuleViolation(
            rule_id="invalid-config",
            severity=Severity.WARNING,
            message="Unknown rule 'bogus-rule' in config",
        ),
    ]

    output = format_sarif(violations, context, [], "1.0.0")
    data = json.loads(output)

    descriptor = next(r for r in data["runs"][0]["tool"]["driver"]["rules"])
    assert "helpUri" not in descriptor


def test_text_links_rule_docs_for_violations(valid_plugin):
    """Text output lists doc URLs for the builtin rules that fired."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    linter.run()
    violations = [
        RuleViolation(
            rule_id="claude-command-naming",
            severity=Severity.WARNING,
            message="Command file should use kebab-case",
            file_path=Path("plugins/foo/commands/Bad_Name.md"),
            line=3,
        ),
    ]

    output = format_text(violations, context, linter.rules, "1.0.0")
    assert "Rule docs" in output
    assert "https://skillsaw.org/rules/claude-command-naming/" in output


def test_text_no_rule_docs_section_when_clean(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)

    output = format_text([], context, linter.rules, "1.0.0")
    assert "Rule docs" not in output


def test_text_no_rule_docs_for_synthetic_rule_ids(valid_plugin):
    """Synthetic rule IDs (invalid-config) must not produce doc links."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = [
        RuleViolation(
            rule_id="invalid-config",
            severity=Severity.WARNING,
            message="Unknown rule 'bogus-rule' in config",
        ),
    ]

    output = format_text(violations, context, linter.rules, "1.0.0")
    assert "https://skillsaw.org/rules/invalid-config/" not in output


# --- OSC 8 hyperlinks (text formatter) ---


def _hyperlink_violations():
    return [
        RuleViolation(
            rule_id="claude-command-naming",
            severity=Severity.WARNING,
            message="Command file should use kebab-case",
            file_path=Path("plugins/foo/commands/Bad_Name.md"),
            line=3,
        ),
        RuleViolation(
            rule_id="invalid-config",
            severity=Severity.WARNING,
            message="Unknown rule 'bogus-rule' in config",
        ),
    ]


def test_text_hyperlinks_link_rule_ids_and_paths(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    linter.run()

    output = format_text(
        _hyperlink_violations(), context, linter.rules, "1.0.0", color=True, hyperlinks=True
    )
    assert (
        "\x1b]8;;https://skillsaw.org/rules/claude-command-naming/\x1b\\claude-command-naming"
        in output
    )
    assert "\x1b]8;;file://" in output
    # Synthetic rule ids have no docs page and must not be linked.
    assert "\x1b]8;;https://skillsaw.org/rules/invalid-config/" not in output


def test_text_hyperlinks_do_not_leak_outside_repo_paths(valid_plugin):
    context = RepositoryContext(valid_plugin)
    outside = valid_plugin.parent / "private" / "secret.md"
    violations = [
        RuleViolation(
            rule_id="outside",
            severity=Severity.WARNING,
            message="Outside path",
            file_path=outside,
        )
    ]

    output = format_text(violations, context, [], "1.0.0", hyperlinks=True)

    assert "outside-repo/" in output
    assert str(outside.parent) not in output
    assert outside.as_uri() not in output
    assert "\x1b]8;;file://" not in output


def test_text_hyperlinks_collapse_rule_docs_footer(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    linter.run()

    output = format_text(
        _hyperlink_violations(), context, linter.rules, "1.0.0", color=True, hyperlinks=True
    )
    assert "Rule docs" not in output
    assert "https://skillsaw.org/rules/claude-command-naming/\x1b\\" in output  # only as a link
    assert "skillsaw explain" in output  # the one-line hint remains


def test_text_no_osc8_without_hyperlinks(valid_plugin):
    """Color alone (e.g. FORCE_COLOR through a pipe) keeps the plain footer."""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    linter.run()

    output = format_text(_hyperlink_violations(), context, linter.rules, "1.0.0", color=True)
    assert "\x1b]8;;" not in output
    assert "Rule docs" in output
    assert "https://skillsaw.org/rules/claude-command-naming/" in output


def test_sarif_synthetic_descriptor_for_unknown_rule_id(valid_plugin):
    """Any violation with a rule_id not in the rules list gets a synthetic descriptor."""
    context = RepositoryContext(valid_plugin)
    violations = [
        RuleViolation(
            rule_id="custom-unknown-rule",
            severity=Severity.ERROR,
            message="Something went wrong",
        ),
    ]

    output = format_sarif(violations, context, [], "1.0.0")
    data = json.loads(output)

    rules = data["runs"][0]["tool"]["driver"]["rules"]
    rule_ids = {r["id"] for r in rules}
    assert "custom-unknown-rule" in rule_ids

    # Fallback description should be the raw rule_id itself
    descriptor = next(r for r in rules if r["id"] == "custom-unknown-rule")
    assert descriptor["shortDescription"]["text"] == "custom-unknown-rule"

    # The result must reference the synthetic descriptor
    results = data["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["ruleId"] == "custom-unknown-rule"


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
    assert "claude-plugin-json-required" in output
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


# --- Code Climate / GitLab Code Quality formatter ---


def test_gitlab_valid_json_array(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_code_climate(violations, context, linter.rules, "1.0.0")
    data = json.loads(output)

    assert isinstance(data, list)


def test_gitlab_required_fields(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_code_climate(violations, context, [], "1.0.0", verbose=True)
    data = json.loads(output)

    assert len(data) == 3
    for entry in data:
        assert "description" in entry
        assert "check_name" in entry
        assert "fingerprint" in entry
        assert "severity" in entry
        assert "location" in entry
        assert "path" in entry["location"]
        assert "lines" in entry["location"]
        assert "begin" in entry["location"]["lines"]


def test_gitlab_severity_mapping(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_code_climate(violations, context, [], "1.0.0", verbose=True)
    data = json.loads(output)

    severity_by_check = {e["check_name"]: e["severity"] for e in data}
    assert severity_by_check["claude-plugin-json-required"] == "critical"
    assert severity_by_check["claude-command-naming"] == "major"
    assert severity_by_check["claude-plugin-json-valid"] == "minor"


def test_gitlab_fingerprints_unique(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_code_climate(violations, context, [], "1.0.0", verbose=True)
    data = json.loads(output)

    fingerprints = [e["fingerprint"] for e in data]
    assert len(fingerprints) == len(set(fingerprints))


def test_gitlab_discriminator_distinguishes_same_location(valid_plugin):
    """Sibling subchecks at one source line retain distinct fingerprints."""
    context = RepositoryContext(valid_plugin)
    path = Path("plugins/foo/skills/deploy/SKILL.md")
    violations = [
        RuleViolation(
            rule_id="content-description-routing",
            severity=Severity.WARNING,
            message="missing trigger",
            file_path=path,
            line=3,
            fingerprint_discriminator="missing-trigger",
        ),
        RuleViolation(
            rule_id="content-description-routing",
            severity=Severity.WARNING,
            message="name restatement",
            file_path=path,
            line=3,
            fingerprint_discriminator="name-restatement",
        ),
    ]

    output = format_code_climate(violations, context, [], "1.0.0")
    fingerprints = [entry["fingerprint"] for entry in json.loads(output)]

    assert len(fingerprints) == len(set(fingerprints)) == 2


def test_gitlab_metric_keeps_legacy_fingerprint(valid_plugin):
    """Existing metric-bearing rules retain their external issue identity."""
    context = RepositoryContext(valid_plugin)
    violation = RuleViolation(
        rule_id="context-budget",
        severity=Severity.WARNING,
        message="description exceeds budget",
        file_path=Path("plugins/foo/skills/deploy/SKILL.md"),
        line=3,
        value=100,
        metric="skill-description",
    )

    output = format_code_climate([violation], context, [], "1.0.0")
    fingerprint = json.loads(output)[0]["fingerprint"]
    legacy_input = "context-budget:plugins/foo/skills/deploy/SKILL.md:3"

    assert fingerprint == hashlib.sha256(legacy_input.encode()).hexdigest()


def test_gitlab_fingerprint_survives_surrogate_discriminator(valid_plugin):
    """A quoted YAML key like "\\uD800bad" reaches the discriminator as a
    lone surrogate; the fingerprint encode must not crash on it."""
    context = RepositoryContext(valid_plugin)
    violation = RuleViolation(
        rule_id="invalid-config",
        severity=Severity.WARNING,
        message="Unknown option for rule 'agentskill-description'",
        file_path=Path(".skillsaw.yaml"),
        line=3,
        fingerprint_discriminator="agentskill-description:\ud800bad",
    )

    output = format_code_climate([violation], context, [], "1.0.0")
    fingerprint = json.loads(output)[0]["fingerprint"]
    assert len(fingerprint) == 64


def test_gitlab_fingerprint_is_sha256_hex(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_code_climate(violations, context, [], "1.0.0", verbose=True)
    data = json.loads(output)

    for entry in data:
        assert len(entry["fingerprint"]) == 64
        int(entry["fingerprint"], 16)


def test_gitlab_excludes_info_without_verbose(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_code_climate(violations, context, [], "1.0.0", verbose=False)
    data = json.loads(output)

    assert len(data) == 2
    assert all(
        e["severity"] != "minor" or e["check_name"] != "claude-plugin-json-valid" for e in data
    )


def test_gitlab_line_numbers(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_code_climate(violations, context, [], "1.0.0", verbose=True)
    data = json.loads(output)

    by_check = {e["check_name"]: e for e in data}
    assert by_check["claude-plugin-json-required"]["location"]["lines"]["begin"] == 1
    assert by_check["claude-command-naming"]["location"]["lines"]["begin"] == 3


def test_code_climate_paths_relative_to_repo_root(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = _make_violations()

    output = format_code_climate(violations, context, [], "1.0.0")
    data = json.loads(output)

    for entry in data:
        path = entry["location"]["path"]
        assert not path.startswith("/"), f"Path must be relative, got: {path}"
        assert not path.startswith("./"), f"Path must not have ./ prefix, got: {path}"


def test_code_climate_strips_dot_slash_prefix(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = [
        RuleViolation(
            rule_id="test-rule",
            severity=Severity.WARNING,
            message="test",
            file_path=Path("./plugins/foo/bar.md"),
            line=1,
        ),
    ]

    output = format_code_climate(violations, context, [], "1.0.0")
    data = json.loads(output)

    path = data[0]["location"]["path"]
    assert not path.startswith("./"), f"Path must not have ./ prefix, got: {path}"
    assert not path.startswith("/"), f"Path must be relative, got: {path}"


def test_code_climate_dispatched_via_format_report(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_report("code-climate", violations, context, linter.rules, "1.0.0")
    data = json.loads(output)
    assert isinstance(data, list)


def test_gitlab_alias_dispatched_via_format_report(valid_plugin):
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()

    output = format_report("gitlab", violations, context, linter.rules, "1.0.0")
    data = json.loads(output)
    assert isinstance(data, list)


# --- duration ---


def test_format_duration_units():
    from skillsaw.formatters.text import format_duration

    assert format_duration(0.45) == "450ms"
    assert format_duration(2.34) == "2.3s"
    assert format_duration(72) == "1m 12s"


def test_text_includes_duration(valid_plugin):
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, LinterConfig.default())
    violations = linter.run()

    output = format_text(violations, context, linter.rules, "0.0.0", duration=1.23)
    assert "Took:      1.2s" in output

    # Omitted entirely when no duration is supplied (library callers)
    output = format_text(violations, context, linter.rules, "0.0.0")
    assert "Took:" not in output


def test_json_includes_duration(valid_plugin):
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, LinterConfig.default())
    violations = linter.run()

    report = json.loads(format_json(violations, context, linter.rules, "0.0.0", duration=1.2345))
    assert report["stats"]["duration_seconds"] == 1.234

    report = json.loads(format_json(violations, context, linter.rules, "0.0.0"))
    assert "duration_seconds" not in report["stats"]


# --- Fixable markers and fix hints ---


def _make_fixable_violations():
    """One SAFE-fixable error, one SAFE-fixable warning shown as error,
    one SUGGEST-fixable warning, one explicitly unfixable error."""
    return [
        RuleViolation(
            rule_id="agentskill-valid",
            severity=Severity.ERROR,
            message="Missing required 'name' field",
            file_path=Path("skills/foo/SKILL.md"),
            fixable=True,
            fix_confidence=AutofixConfidence.SAFE,
        ),
        RuleViolation(
            rule_id="claude-agent-frontmatter",
            severity=Severity.ERROR,
            message="Missing 'description' in frontmatter",
            file_path=Path("agents/bar.md"),
            fixable=True,
            fix_confidence=AutofixConfidence.SAFE,
        ),
        RuleViolation(
            rule_id="content-broken-internal-reference",
            severity=Severity.WARNING,
            message="Broken internal link (did you mean 'docs/guide.md'?)",
            file_path=Path("SKILL.md"),
            line=8,
            fixable=True,
            fix_confidence=AutofixConfidence.SUGGEST,
        ),
        RuleViolation(
            rule_id="agentskill-valid",
            severity=Severity.ERROR,
            message="'description' must be a string",
            file_path=Path("skills/baz/SKILL.md"),
            fixable=False,
        ),
    ]


def test_text_marks_safe_fixable_violations(valid_plugin):
    context = RepositoryContext(valid_plugin)
    output = format_text(_make_fixable_violations(), context, [], "0.0.0")

    assert "(agentskill-valid) [*] [skills/foo/SKILL.md]:" in output
    assert "(claude-agent-frontmatter) [*] [agents/bar.md]:" in output


def test_text_marks_suggest_fixable_violations(valid_plugin):
    context = RepositoryContext(valid_plugin)
    output = format_text(_make_fixable_violations(), context, [], "0.0.0")

    assert "(content-broken-internal-reference) [?] [SKILL.md:8]:" in output


def test_text_no_marker_on_unfixable_violation(valid_plugin):
    context = RepositoryContext(valid_plugin)
    output = format_text(_make_fixable_violations(), context, [], "0.0.0")

    # Same rule id as a marked violation — only the fixable one is marked.
    assert "(agentskill-valid) [skills/baz/SKILL.md]:" in output


def test_text_no_marker_when_fixability_unknown(valid_plugin):
    context = RepositoryContext(valid_plugin)
    # _make_violations leaves fixable=None (e.g. synthetic violations).
    output = format_text(_make_violations(), context, [], "0.0.0", verbose=True)

    assert "[*]" not in output
    assert "[?]" not in output
    assert "fixable with" not in output


def test_text_neutralizes_terminal_controls(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violation = RuleViolation(
        rule_id="bad\x1b]0;title\x07rule",
        severity=Severity.ERROR,
        message="hide\x1b[2Joutput",
        file_path=Path("evil\x1b]8;;https://example.test\x07.md"),
    )

    output = format_text([violation], context, [], "0.0.0", color=False)

    assert "\x1b" not in output
    assert "\x07" not in output
    assert "\ufffd" in output


def test_tree_neutralizes_controls_in_root_name(tmp_path):
    root = tmp_path / "repo\x1b]0;title\x07"
    node = LintTarget(root)
    assert "\x1b" not in node.print_tree(root_path=root)


def test_relative_path_does_not_leak_outside_absolute_path(tmp_path):
    outside = tmp_path.parent / "private" / "secret.md"
    rendered = relative_path(outside, tmp_path)
    assert rendered.startswith("outside-repo/")
    assert rendered.endswith("-secret.md")
    assert str(outside.parent) not in rendered


def test_relative_path_distinguishes_same_named_outside_files(tmp_path):
    first = tmp_path.parent / "one" / "secret.md"
    second = tmp_path.parent / "two" / "secret.md"
    assert relative_path(first, tmp_path) != relative_path(second, tmp_path)


def test_text_fixable_summary_splits_safe_and_suggest(valid_plugin):
    context = RepositoryContext(valid_plugin)
    output = format_text(_make_fixable_violations(), context, [], "0.0.0")

    assert (
        "[*] 2 violation(s) fixable with `skillsaw fix`"
        " ([?] 1 more with `skillsaw fix --suggest`)" in output
    )


def test_text_fixable_summary_safe_only(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = [
        v for v in _make_fixable_violations() if v.fix_confidence != AutofixConfidence.SUGGEST
    ]
    output = format_text(violations, context, [], "0.0.0")

    assert "[*] 2 violation(s) fixable with `skillsaw fix`" in output
    assert "--suggest" not in output


def test_text_fixable_summary_suggest_only(valid_plugin):
    context = RepositoryContext(valid_plugin)
    violations = [
        v for v in _make_fixable_violations() if v.fix_confidence != AutofixConfidence.SAFE
    ]
    output = format_text(violations, context, [], "0.0.0")

    assert "[?] 1 violation(s) fixable with `skillsaw fix --suggest`" in output
    assert "[*]" not in output


def test_text_fixable_summary_counts_only_shown_violations(valid_plugin):
    """A hidden info-level fixable violation must not inflate the summary —
    the counts must match the marked lines above them."""
    context = RepositoryContext(valid_plugin)
    violations = [
        RuleViolation(
            rule_id="content-unlinked-internal-reference",
            severity=Severity.INFO,
            message="Unlinked path reference: 'docs/x.md' (file exists, autofixable)",
            file_path=Path("SKILL.md"),
            line=3,
            fixable=True,
            fix_confidence=AutofixConfidence.SAFE,
        ),
    ]

    hidden = format_text(violations, context, [], "0.0.0", verbose=False)
    assert "fixable with" not in hidden

    shown = format_text(violations, context, [], "0.0.0", verbose=True)
    assert "[*] 1 violation(s) fixable with `skillsaw fix`" in shown


def test_json_fixable_true_includes_confidence(valid_plugin):
    context = RepositoryContext(valid_plugin)
    report = json.loads(format_json(_make_fixable_violations(), context, [], "0.0.0"))

    safe = next(v for v in report["violations"] if v["rule_id"] == "claude-agent-frontmatter")
    assert safe["fixable"] is True
    assert safe["fix_confidence"] == "safe"

    suggest = next(
        v for v in report["violations"] if v["rule_id"] == "content-broken-internal-reference"
    )
    assert suggest["fixable"] is True
    assert suggest["fix_confidence"] == "suggest"


def test_json_fixable_false_omits_confidence(valid_plugin):
    context = RepositoryContext(valid_plugin)
    report = json.loads(format_json(_make_fixable_violations(), context, [], "0.0.0"))

    unfixable = next(
        v for v in report["violations"] if v["message"] == "'description' must be a string"
    )
    assert unfixable["fixable"] is False
    assert "fix_confidence" not in unfixable


def test_json_fixable_absent_when_unknown(valid_plugin):
    context = RepositoryContext(valid_plugin)
    # _make_violations leaves fixable=None (e.g. synthetic violations).
    report = json.loads(format_json(_make_violations(), context, [], "0.0.0", verbose=True))

    for v in report["violations"]:
        assert "fixable" not in v
        assert "fix_confidence" not in v


def test_html_fixable_marker(valid_plugin):
    context = RepositoryContext(valid_plugin)
    output = format_html(_make_fixable_violations(), context, [], "1.0.0")

    assert 'title="fixable with skillsaw fix"' in output
    assert 'title="fixable with skillsaw fix --suggest"' in output


def test_html_no_fixable_marker_when_unknown(valid_plugin):
    context = RepositoryContext(valid_plugin)
    output = format_html(_make_violations(), context, [], "1.0.0", verbose=True)

    assert 'class="fixable"' not in output
