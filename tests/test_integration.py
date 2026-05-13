"""
End-to-end integration tests for the skillsaw CLI.

Each test copies a static fixture from tests/fixtures/ into a temp
directory, invokes ``python -m skillsaw lint --format json -v`` via
subprocess, and asserts on the parsed JSON output: rule IDs, severities,
violation counts, line numbers, exit codes, and stats.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


# ── Helpers ──────────────────────────────────────────────────────


def run_lint(path, *extra_args, config=None, verbose=True, fmt="json"):
    args = [sys.executable, "-m", "skillsaw", "lint"]
    if fmt:
        args.extend(["--format", fmt])
    if verbose:
        args.append("-v")
    if config:
        args.extend(["-c", str(config)])
    args.extend(extra_args)
    args.append(str(path))
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    output = None
    if fmt == "json" and result.stdout.strip():
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return {
        "rc": result.returncode,
        "out": output,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def violations(r):
    return r["out"]["violations"] if r["out"] else []


def by_rule(r):
    grouped = {}
    for v in violations(r):
        grouped.setdefault(v["rule_id"], []).append(v)
    return grouped


def rule_ids(r):
    return {v["rule_id"] for v in violations(r)}


def summary(r):
    return r["out"]["summary"] if r["out"] else {}


def copy_fixture(name, tmp_path):
    src = FIXTURES / name
    dst = tmp_path / name.replace("/", "_")
    shutil.copytree(src, dst)
    return dst


# ── Single Plugin ────────────────────────────────────────────────


@pytest.mark.integration
class TestSinglePlugin:

    def test_clean_plugin_passes(self, tmp_path):
        repo = copy_fixture("single-plugin/clean", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 0
        assert summary(r)["errors"] == 0
        assert summary(r)["warnings"] == 0

    def test_broken_plugin_detects_violations(self, tmp_path):
        repo = copy_fixture("single-plugin/broken", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 1

        ids = rule_ids(r)
        assert "plugin-json-valid" in ids
        assert "plugin-naming" in ids
        assert "plugin-readme" in ids
        assert "command-naming" in ids
        assert "command-frontmatter" in ids
        assert "agent-frontmatter" in ids

        s = summary(r)
        assert s["errors"] >= 4
        assert s["warnings"] >= 4

    def test_broken_plugin_violation_details(self, tmp_path):
        repo = copy_fixture("single-plugin/broken", tmp_path)
        r = run_lint(repo)
        grouped = by_rule(r)

        naming = grouped["plugin-naming"]
        assert any("kebab-case" in v["message"] for v in naming)

        frontmatter = grouped["command-frontmatter"]
        assert any("Missing frontmatter" in v["message"] for v in frontmatter)

        agent = grouped["agent-frontmatter"]
        assert any("name" in v["message"].lower() for v in agent)
        assert any("description" in v["message"].lower() for v in agent)

    def test_embedded_secrets_detected(self, tmp_path):
        repo = copy_fixture("single-plugin/with-secrets", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 1
        assert "content-embedded-secrets" in rule_ids(r)

        secrets = by_rule(r)["content-embedded-secrets"]
        assert len(secrets) >= 1
        assert secrets[0]["line"] is not None
        assert "setup.md" in secrets[0]["file_path"]


# ── Marketplace ──────────────────────────────────────────────────


@pytest.mark.integration
class TestMarketplace:

    def test_clean_marketplace_passes(self, tmp_path):
        repo = copy_fixture("marketplace/clean", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 0
        assert summary(r)["errors"] == 0
        assert summary(r)["warnings"] == 0

    def test_broken_marketplace_detects_violations(self, tmp_path):
        repo = copy_fixture("marketplace/broken", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 1
        assert "marketplace-json-valid" in rule_ids(r)

    def test_marketplace_stats(self, tmp_path):
        repo = copy_fixture("marketplace/clean", tmp_path)
        r = run_lint(repo)
        stats = r["out"]["stats"]
        assert "marketplace" in stats["repo_types"]
        assert len(stats["plugins"]) == 2


# ── Agentskills ──────────────────────────────────────────────────


@pytest.mark.integration
class TestAgentskills:

    def test_clean_agentskills_passes(self, tmp_path):
        repo = copy_fixture("agentskills/clean", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 0
        assert summary(r)["errors"] == 0
        assert summary(r)["warnings"] == 0

    def test_broken_agentskills_detects_violations(self, tmp_path):
        repo = copy_fixture("agentskills/broken", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 1

        ids = rule_ids(r)
        assert "agentskill-valid" in ids or "skill-frontmatter" in ids

        all_violations = violations(r)
        assert any("name" in v["message"].lower() for v in all_violations)

    def test_agentskills_stats(self, tmp_path):
        repo = copy_fixture("agentskills/clean", tmp_path)
        r = run_lint(repo)
        stats = r["out"]["stats"]
        assert "agentskills" in stats["repo_types"]
        assert len(stats["skills"]) == 2


# ── Dot-Claude ───────────────────────────────────────────────────


@pytest.mark.integration
class TestDotClaude:

    def test_clean_dot_claude_passes(self, tmp_path):
        repo = copy_fixture("dot-claude/clean", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 0
        assert summary(r)["errors"] == 0
        assert summary(r)["warnings"] == 0

    def test_broken_dot_claude_content_violations(self, tmp_path):
        repo = copy_fixture("dot-claude/broken", tmp_path)
        r = run_lint(repo)

        ids = rule_ids(r)
        assert "content-weak-language" in ids
        assert "content-tautological" in ids

        weak = by_rule(r)["content-weak-language"]
        assert len(weak) >= 3
        assert all(v["line"] is not None for v in weak)
        assert all("CLAUDE.md" in v["file_path"] for v in weak)

        taut = by_rule(r)["content-tautological"]
        assert len(taut) >= 2

    def test_dot_claude_stats(self, tmp_path):
        repo = copy_fixture("dot-claude/clean", tmp_path)
        r = run_lint(repo)
        stats = r["out"]["stats"]
        assert "dot-claude" in stats["repo_types"]


# ── CodeRabbit ───────────────────────────────────────────────────


@pytest.mark.integration
class TestCodeRabbit:

    def test_clean_coderabbit_passes(self, tmp_path):
        repo = copy_fixture("coderabbit/clean", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 0
        assert summary(r)["errors"] == 0

    def test_broken_coderabbit_detects_yaml_error(self, tmp_path):
        repo = copy_fixture("coderabbit/broken", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 1
        assert "coderabbit-yaml-valid" in rule_ids(r)

        violations_list = by_rule(r)["coderabbit-yaml-valid"]
        assert violations_list[0]["severity"] == "error"
        assert ".coderabbit.yaml" in violations_list[0]["file_path"]


# ── APM ──────────────────────────────────────────────────────────


@pytest.mark.integration
class TestApm:

    def test_clean_apm_passes(self, tmp_path):
        repo = copy_fixture("apm/clean", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 0
        assert summary(r)["errors"] == 0
        assert summary(r)["warnings"] == 0

    def test_broken_apm_detects_violations(self, tmp_path):
        repo = copy_fixture("apm/broken", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 1

        ids = rule_ids(r)
        assert "apm-yaml-valid" in ids
        assert "apm-structure-valid" in ids

        apm_violations = by_rule(r)["apm-yaml-valid"]
        assert any("description" in v["message"].lower() for v in apm_violations)


# ── Inline Suppression ───────────────────────────────────────────


@pytest.mark.integration
class TestSuppression:

    def test_single_rule_suppression(self, tmp_path):
        """Content between disable/enable directives should be suppressed."""
        repo = copy_fixture("suppression/single-rule", tmp_path)
        r = run_lint(repo)
        assert "content-weak-language" not in rule_ids(r)

    def test_blanket_suppression(self, tmp_path):
        """Disable without rule IDs suppresses all rules in that range."""
        repo = copy_fixture("suppression/all-rules", tmp_path)
        r = run_lint(repo)
        content_violations = [
            v
            for v in violations(r)
            if v["rule_id"].startswith("content-") and v["rule_id"] != "content-actionability-score"
        ]
        assert len(content_violations) == 0

    def test_next_line_suppression(self, tmp_path):
        """disable-next-line suppresses only the immediately following line."""
        repo = copy_fixture("suppression/next-line", tmp_path)
        r = run_lint(repo)
        weak = by_rule(r).get("content-weak-language", [])
        assert len(weak) >= 1
        assert all(v["line"] != 18 for v in weak)

    def test_multi_rule_suppression(self, tmp_path):
        """Comma-separated rule IDs suppress all listed rules."""
        repo = copy_fixture("suppression/multi-rule", tmp_path)
        r = run_lint(repo)
        ids = rule_ids(r)
        assert "content-weak-language" not in ids
        assert "content-tautological" not in ids


# ── Config Features ──────────────────────────────────────────────


@pytest.mark.integration
class TestConfigFeatures:

    def test_global_exclude_suppresses_file(self, tmp_path):
        repo = copy_fixture("config/exclude-test", tmp_path)
        r = run_lint(repo)
        violated_files = {v["file_path"] for v in violations(r)}
        assert not any("generated.md" in f for f in violated_files)

    def test_per_rule_exclude(self, tmp_path):
        """Per-rule exclude suppresses one file but not another."""
        repo = copy_fixture("config/per-rule-exclude", tmp_path)
        r = run_lint(repo)
        frontmatter = by_rule(r).get("command-frontmatter", [])
        files = {v["file_path"] for v in frontmatter}
        assert any("real-cmd.md" in f for f in files)
        assert not any("vendor-cmd.md" in f for f in files)

    def test_disable_rule_via_config(self, tmp_path):
        repo = copy_fixture("config/disable-rules", tmp_path)
        r = run_lint(repo)
        assert "command-frontmatter" not in rule_ids(r)
        rules_run = r["out"]["stats"]["rules_run"]
        assert "command-frontmatter" not in rules_run

    def test_strict_mode_exits_nonzero_on_warnings(self, tmp_path):
        repo = copy_fixture("config/strict-mode", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 1
        assert summary(r)["errors"] == 0
        assert summary(r)["warnings"] >= 1

    def test_content_paths_scans_extra_files(self, tmp_path):
        repo = copy_fixture("config/content-paths", tmp_path)
        r = run_lint(repo)
        weak = by_rule(r).get("content-weak-language", [])
        docs_violations = [v for v in weak if "guidelines.md" in v["file_path"]]
        assert len(docs_violations) >= 1


# ── Exit Codes ───────────────────────────────────────────────────


@pytest.mark.integration
class TestExitCodes:

    def test_exit_0_on_clean(self, tmp_path):
        repo = copy_fixture("single-plugin/clean", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 0

    def test_exit_1_on_errors(self, tmp_path):
        repo = copy_fixture("single-plugin/broken", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 1

    def test_exit_0_on_warnings_only(self, tmp_path):
        """Missing README produces a warning but no errors — exit 0 without strict."""
        repo = copy_fixture("single-plugin/with-secrets", tmp_path)
        # Remove the secret so only the missing-README warning remains
        (repo / "commands" / "setup.md").write_text(
            "---\ndescription: Setup\n---\n\n## Name\nsecrets-test:setup\n\n"
            "## Synopsis\n```\n/secrets-test:setup\n```\n\n"
            "## Description\nSetup command.\n\n## Implementation\n1. Run setup\n"
        )
        r = run_lint(repo)
        assert r["rc"] == 0
        assert summary(r)["warnings"] >= 1
        assert summary(r)["errors"] == 0

    def test_exit_1_on_warnings_with_strict(self, tmp_path):
        """Same warnings-only fixture but with --strict — exit 1."""
        repo = copy_fixture("single-plugin/with-secrets", tmp_path)
        (repo / "commands" / "setup.md").write_text(
            "---\ndescription: Setup\n---\n\n## Name\nsecrets-test:setup\n\n"
            "## Synopsis\n```\n/secrets-test:setup\n```\n\n"
            "## Description\nSetup command.\n\n## Implementation\n1. Run setup\n"
        )
        r = run_lint(repo, "--strict")
        assert r["rc"] == 1


# ── Output Formats ───────────────────────────────────────────────


@pytest.mark.integration
class TestOutputFormats:

    def test_json_output_structure(self, tmp_path):
        repo = copy_fixture("single-plugin/clean", tmp_path)
        r = run_lint(repo)
        out = r["out"]
        assert "version" in out
        assert "stats" in out
        assert "violations" in out
        assert "summary" in out
        stats = out["stats"]
        assert "repo_type" in stats
        assert "repo_types" in stats
        assert "plugins" in stats
        assert "skills" in stats
        assert "rules_run" in stats
        s = out["summary"]
        assert "errors" in s
        assert "warnings" in s
        assert "info" in s

    def test_verbose_includes_info(self, tmp_path):
        repo = copy_fixture("single-plugin/clean", tmp_path)
        verbose = run_lint(repo, verbose=True)
        quiet = run_lint(repo, verbose=False)
        verbose_info = [v for v in violations(verbose) if v["severity"] == "info"]
        quiet_info = [v for v in violations(quiet) if v["severity"] == "info"]
        assert len(verbose_info) > len(quiet_info)

    def test_sarif_output(self, tmp_path):
        repo = copy_fixture("single-plugin/broken", tmp_path)
        sarif_path = tmp_path / "report.sarif"
        run_lint(repo, "--output", str(sarif_path))
        assert sarif_path.exists()
        sarif = json.loads(sarif_path.read_text())
        assert sarif["version"] == "2.1.0"
        assert "$schema" in sarif
        assert len(sarif["runs"]) == 1
