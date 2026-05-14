"""
End-to-end integration tests for the skillsaw CLI.

Each test copies a static fixture from tests/fixtures/ into a temp
directory, invokes ``python -m skillsaw lint --format json -v`` via
subprocess, and asserts on the parsed JSON output: rule IDs, severities,
violation counts, line numbers, exit codes, and stats.

Fixtures may contain ``<!-- skillsaw-assert rule-id -->`` directives.
Each directive declares that the NEXT non-directive, non-blank line must
trigger a violation with the given rule-id.  The parametrized
``test_assert_directives`` test collects these expectations and verifies
them against the actual linter output.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

_ASSERT_RE = re.compile(
    r"<!--\s*skillsaw-assert\s+([\w,\s-]+)\s*-->",
    re.IGNORECASE,
)


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
        output = json.loads(result.stdout)
    return {
        "rc": result.returncode,
        "out": output,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def violations(r):
    return r["out"]["violations"] if r["out"] else []


def by_rule(r):
    grouped: Dict[str, list] = {}
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


# ── Assert-directive infrastructure ──────────────────────────────


@dataclass
class ExpectedViolation:
    file_path: str
    line: int
    rule_ids: Set[str]


def collect_assertions(fixture_dir: Path) -> List[ExpectedViolation]:
    """Walk *fixture_dir* for ``<!-- skillsaw-assert rule-id -->`` directives.

    Returns one ``ExpectedViolation`` per directive, pointing at the first
    non-blank, non-directive line that follows the comment.
    """
    expectations: List[ExpectedViolation] = []
    for md_file in sorted(fixture_dir.rglob("*.md")):
        lines = md_file.read_text().splitlines()
        pending_rule_ids: Set[str] = set()
        for lineno_0, raw in enumerate(lines):
            m = _ASSERT_RE.search(raw)
            if m:
                for rid in m.group(1).split(","):
                    rid = rid.strip()
                    if rid:
                        pending_rule_ids.add(rid)
                continue
            if pending_rule_ids and raw.strip():
                rel = str(md_file.relative_to(fixture_dir))
                expectations.append(
                    ExpectedViolation(
                        file_path=rel,
                        line=lineno_0 + 1,
                        rule_ids=set(pending_rule_ids),
                    )
                )
                pending_rule_ids = set()
    return expectations


def verify_assertions(result, assertions: List[ExpectedViolation]) -> List[str]:
    """Return a list of failure messages for unmatched assertions."""
    actual = violations(result)
    failures: List[str] = []
    for exp in assertions:
        for rid in exp.rule_ids:
            matched = any(
                v["rule_id"] == rid and v["file_path"] == exp.file_path and v["line"] == exp.line
                for v in actual
            )
            if not matched:
                failures.append(
                    f"Expected {rid} at {exp.file_path}:{exp.line} — not found in output"
                )
    return failures


def _fixture_dirs_with_assertions():
    """Yield (fixture_name, fixture_path) for fixtures containing assert directives."""
    for md_file in sorted(FIXTURES.rglob("*.md")):
        if _ASSERT_RE.search(md_file.read_text()):
            rel = md_file.relative_to(FIXTURES)
            top_fixture = FIXTURES / rel.parts[0] / rel.parts[1]
            yield str(top_fixture.relative_to(FIXTURES)), top_fixture


def _deduplicated_fixture_dirs():
    seen: Set[str] = set()
    result = []
    for name, path in _fixture_dirs_with_assertions():
        if name not in seen:
            seen.add(name)
            result.append(pytest.param(name, id=name))
    return result


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
        assert len(stats["plugins"]) == 3


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
        assert len(stats["skills"]) == 4


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


# ── Promptfoo ────────────────────────────────────────────────────


@pytest.mark.integration
class TestPromptfoo:

    def test_nested_promptfoo_config_detected(self, tmp_path):
        repo = copy_fixture("promptfoo/nested-config", tmp_path)
        r = run_lint(repo)
        stats = r["out"]["stats"]
        assert "promptfoo" in stats["repo_types"]

    def test_nested_promptfoo_config_validates(self, tmp_path):
        repo = copy_fixture("promptfoo/nested-config", tmp_path)
        r = run_lint(repo)
        promptfoo_violations = [v for v in violations(r) if v["rule_id"].startswith("promptfoo-")]
        assert len(promptfoo_violations) == 0


# ── Inline Suppression ───────────────────────────────────────────


@pytest.mark.integration
class TestSuppression:

    def test_single_rule_suppression(self, tmp_path):
        """Content between disable/enable directives should be suppressed."""
        repo = copy_fixture("suppression/single-rule", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 0
        assert r["out"] is not None
        assert "content-weak-language" not in rule_ids(r)

    def test_blanket_suppression(self, tmp_path):
        """Disable without rule IDs suppresses all rules in that range."""
        repo = copy_fixture("suppression/all-rules", tmp_path)
        r = run_lint(repo)
        assert r["out"] is not None
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
        assert r["out"] is not None
        weak = by_rule(r).get("content-weak-language", [])
        assert len(weak) >= 1
        assert all(v["line"] != 18 for v in weak)

    def test_multi_rule_suppression(self, tmp_path):
        """Comma-separated rule IDs suppress all listed rules."""
        repo = copy_fixture("suppression/multi-rule", tmp_path)
        r = run_lint(repo)
        assert r["rc"] == 0
        assert r["out"] is not None
        ids = rule_ids(r)
        assert "content-weak-language" not in ids
        assert "content-tautological" not in ids


# ── Config Features ──────────────────────────────────────────────


@pytest.mark.integration
class TestConfigFeatures:

    def test_global_exclude_suppresses_file(self, tmp_path):
        repo = copy_fixture("config/exclude-test", tmp_path)
        r = run_lint(repo)
        assert r["out"] is not None
        violated_files = {v["file_path"] for v in violations(r)}
        assert not any("generated.md" in f for f in violated_files)

    def test_per_rule_exclude(self, tmp_path):
        """Per-rule exclude suppresses one file but not another."""
        repo = copy_fixture("config/per-rule-exclude", tmp_path)
        r = run_lint(repo)
        assert r["out"] is not None
        frontmatter = by_rule(r).get("command-frontmatter", [])
        files = {v["file_path"] for v in frontmatter}
        assert any("real-cmd.md" in f for f in files)
        assert not any("vendor-cmd.md" in f for f in files)

    def test_disable_rule_via_config(self, tmp_path):
        repo = copy_fixture("config/disable-rules", tmp_path)
        r = run_lint(repo)
        assert r["out"] is not None
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


# ── Assert Directives (data-driven) ─────────────────────────────


@pytest.mark.integration
class TestAssertDirectives:
    """Verify ``<!-- skillsaw-assert rule-id -->`` directives in fixtures.

    Each fixture containing assert directives is discovered automatically.
    The test runs the linter against the fixture and checks that every
    asserted rule fires on the expected line.
    """

    @pytest.mark.parametrize("fixture_name", _deduplicated_fixture_dirs())
    def test_assert_directives(self, fixture_name, tmp_path):
        repo = copy_fixture(fixture_name, tmp_path)
        assertions = collect_assertions(repo)
        assert assertions, f"No assert directives found in {fixture_name}"

        r = run_lint(repo)
        failures = verify_assertions(r, assertions)
        if failures:
            actual = violations(r)
            detail = "\n".join(f"  - {f}" for f in failures)
            actual_summary = "\n".join(
                f"  {v['rule_id']} @ {v['file_path']}:{v['line']}" for v in actual
            )
            pytest.fail(
                f"Assert directive mismatches in {fixture_name}:\n{detail}"
                f"\n\nActual violations:\n{actual_summary}"
            )


# ── Rule Coverage ───────────────────────────────────────────────


BROKEN_FIXTURES = [
    "single-plugin/broken",
    "single-plugin/with-secrets",
    "single-plugin/content-violations",
    "single-plugin/mcp-broken",
    "single-plugin/context-budget",
    "marketplace/broken",
    "agentskills/broken",
    "dot-claude/broken",
    "coderabbit/broken",
    "apm/broken",
]

CLEAN_FIXTURES = [
    "single-plugin/clean",
    "marketplace/clean",
    "agentskills/clean",
    "dot-claude/clean",
    "coderabbit/clean",
    "apm/clean",
]

OPT_IN_RULES = {
    "command-sections",
    "command-name-format",
    "mcp-prohibited",
    "agentskill-structure",
    "agentskill-evals-required",
    "promptfoo-assertions",
    "promptfoo-metadata",
}


@pytest.mark.integration
class TestRuleCoverage:
    """Regression guard: every rule must produce a violation in at least one fixture."""

    def test_every_rule_fires_somewhere(self, tmp_path):
        """Every rule must produce a violation in at least one fixture."""
        from skillsaw.config import LinterConfig

        all_rule_ids = set(LinterConfig.default().rules.keys())
        fired: Set[str] = set()

        for fixture_name in BROKEN_FIXTURES:
            repo = copy_fixture(fixture_name, tmp_path / fixture_name.replace("/", "_"))
            r = run_lint(repo)
            fired |= rule_ids(r)

        # Opt-in rules need explicit config
        repo = copy_fixture("config/opt-in-rules", tmp_path / "config_opt-in-rules")
        config = repo / ".skillsaw.yaml"
        r = run_lint(repo, config=config)
        fired |= rule_ids(r)

        missing = all_rule_ids - fired
        assert not missing, (
            f"Rules without test coverage ({len(missing)}): {sorted(missing)}\n"
            "Add broken fixtures that trigger these rules."
        )

    def test_all_clean_fixtures_pass(self, tmp_path):
        """Every clean fixture must exit 0 with no errors or warnings."""
        for fixture_name in CLEAN_FIXTURES:
            repo = copy_fixture(fixture_name, tmp_path / fixture_name.replace("/", "_"))
            r = run_lint(repo)
            s = summary(r)
            assert r["rc"] == 0, f"{fixture_name}: expected exit 0, got {r['rc']}"
            assert s["errors"] == 0, f"{fixture_name}: unexpected errors"
            assert s["warnings"] == 0, f"{fixture_name}: unexpected warnings"


# ── Opt-In Rules ────────────────────────────────────────────────


@pytest.mark.integration
class TestOptInRules:
    """Verify that opt-in rules fire only when explicitly enabled."""

    def test_opt_in_rules_fire_when_enabled(self, tmp_path):
        repo = copy_fixture("config/opt-in-rules", tmp_path)
        config = repo / ".skillsaw.yaml"
        r = run_lint(repo, config=config)
        ids = rule_ids(r)
        for rule in OPT_IN_RULES:
            assert rule in ids, f"Opt-in rule '{rule}' did not fire with enabled: true"

    def test_opt_in_rules_silent_by_default(self, tmp_path):
        repo = copy_fixture("config/opt-in-rules", tmp_path)
        (repo / ".skillsaw.yaml").unlink()
        r = run_lint(repo)
        ids = rule_ids(r)
        for rule in OPT_IN_RULES:
            assert rule not in ids, f"Opt-in rule '{rule}' fired without being enabled"


# ── Required Fields / Required Metadata ────────────────────────


@pytest.mark.integration
class TestRequiredFieldsConfig:
    """Verify that required-fields and required-metadata config options work end-to-end."""

    def test_complete_skill_passes(self, tmp_path):
        repo = copy_fixture("config/required-fields", tmp_path)
        r = run_lint(repo, config=repo / ".skillsaw.yaml")
        assert r["out"] is not None, f"Expected JSON output, got rc={r['rc']} stderr={r['stderr']}"
        vs = [
            v
            for v in violations(r)
            if "complete-skill" in v["file_path"] and v["rule_id"] == "agentskill-valid"
        ]
        assert len(vs) == 0, f"Complete skill should have no agentskill-valid violations: {vs}"

    def test_missing_required_fields_reported(self, tmp_path):
        repo = copy_fixture("config/required-fields", tmp_path)
        r = run_lint(repo, config=repo / ".skillsaw.yaml")
        assert r["out"] is not None, f"Expected JSON output, got rc={r['rc']} stderr={r['stderr']}"
        vs = [
            v
            for v in violations(r)
            if "missing-fields-skill" in v["file_path"] and v["rule_id"] == "agentskill-valid"
        ]
        messages = [v["message"] for v in vs]
        assert any("Missing required field 'license'" in m for m in messages)
        assert any("metadata" in m.lower() for m in messages)
        license_v = next(v for v in vs if "Missing required field 'license'" in v["message"])
        assert license_v.get("line") is None

    def test_missing_metadata_key_reported(self, tmp_path):
        repo = copy_fixture("config/required-fields", tmp_path)
        r = run_lint(repo, config=repo / ".skillsaw.yaml")
        assert r["out"] is not None, f"Expected JSON output, got rc={r['rc']} stderr={r['stderr']}"
        vs = [
            v
            for v in violations(r)
            if "missing-metadata-key" in v["file_path"] and v["rule_id"] == "agentskill-valid"
        ]
        messages = [v["message"] for v in vs]
        assert any("Missing required metadata key 'org'" in m for m in messages)
        assert not any("Missing required metadata key 'author'" in m for m in messages)
        org_v = next(v for v in vs if "Missing required metadata key 'org'" in v["message"])
        assert org_v.get("line") is not None

    def test_no_extra_violations_without_config(self, tmp_path):
        """Without required-fields config, no extra violations are raised."""
        repo = copy_fixture("config/required-fields", tmp_path)
        (repo / ".skillsaw.yaml").unlink()
        r = run_lint(repo)
        assert r["out"] is not None, f"Expected JSON output, got rc={r['rc']} stderr={r['stderr']}"
        vs = [
            v
            for v in violations(r)
            if "Missing required field" in v["message"]
            or "Missing required metadata key" in v["message"]
        ]
        assert len(vs) == 0, f"Should have no required-field violations without config: {vs}"


class TestUnlinkedInternalReferenceAutofix:
    """Integration tests for content-unlinked-internal-reference autofix via CLI."""

    def _run_fix(self, path, *extra_args):
        args = [sys.executable, "-m", "skillsaw", "fix"]
        args.extend(extra_args)
        args.append(str(path))
        return subprocess.run(args, capture_output=True, text=True, timeout=60)

    def test_fix_duplicate_paths_via_cli(self, tmp_path):
        """CLI fix wraps duplicate bare paths without double-wrapping."""
        repo = copy_fixture("autofix/unlinked-ref-duplicate-paths", tmp_path)
        r = run_lint(repo)
        unlinked = [
            v for v in violations(r) if v["rule_id"] == "content-unlinked-internal-reference"
        ]
        assert len(unlinked) == 2

        result = self._run_fix(repo)
        assert result.returncode == 0

        fixed = (repo / "CLAUDE.md").read_text()
        assert fixed.count("[scripts/test.py](scripts/test.py)") == 2
        assert "[[scripts/test.py]" not in fixed

        r2 = run_lint(repo)
        remaining = [
            v for v in violations(r2) if v["rule_id"] == "content-unlinked-internal-reference"
        ]
        assert len(remaining) == 0

    def test_fix_multiple_different_paths_via_cli(self, tmp_path):
        """CLI fix wraps multiple different bare paths correctly."""
        repo = copy_fixture("autofix/unlinked-ref-multiple-paths", tmp_path)
        r = run_lint(repo)
        unlinked = [
            v for v in violations(r) if v["rule_id"] == "content-unlinked-internal-reference"
        ]
        assert len(unlinked) == 3

        result = self._run_fix(repo)
        assert result.returncode == 0

        fixed = (repo / "CLAUDE.md").read_text()
        assert "[docs/guide.md](docs/guide.md)" in fixed
        assert "[scripts/run.sh](scripts/run.sh)" in fixed
        assert "[src/app.py](src/app.py)" in fixed
        assert "[[" not in fixed

        r2 = run_lint(repo)
        remaining = [
            v for v in violations(r2) if v["rule_id"] == "content-unlinked-internal-reference"
        ]
        assert len(remaining) == 0

    def test_fix_mixed_duplicates_and_unique_paths_via_cli(self, tmp_path):
        """CLI fix handles a mix of duplicate and unique paths."""
        repo = copy_fixture("autofix/unlinked-ref-mixed", tmp_path)
        r = run_lint(repo)
        unlinked = [
            v for v in violations(r) if v["rule_id"] == "content-unlinked-internal-reference"
        ]
        assert len(unlinked) == 4

        result = self._run_fix(repo)
        assert result.returncode == 0

        fixed = (repo / "CLAUDE.md").read_text()
        assert fixed.count("[src/main.py](src/main.py)") == 2
        assert fixed.count("[docs/api.md](docs/api.md)") == 2
        assert "[[" not in fixed
        assert "](src/main.py)](src/main.py)" not in fixed
        assert "](docs/api.md)](docs/api.md)" not in fixed

        r2 = run_lint(repo)
        remaining = [
            v for v in violations(r2) if v["rule_id"] == "content-unlinked-internal-reference"
        ]
        assert len(remaining) == 0

    def test_fix_is_idempotent_via_cli(self, tmp_path):
        """Running fix twice produces no further changes."""
        repo = copy_fixture("autofix/unlinked-ref-duplicate-paths", tmp_path)
        self._run_fix(repo)
        content_after_first = (repo / "CLAUDE.md").read_text()

        self._run_fix(repo)
        content_after_second = (repo / "CLAUDE.md").read_text()

        assert content_after_first == content_after_second
        assert content_after_second.count("[scripts/test.py](scripts/test.py)") == 2

    def test_fix_leaves_already_linked_paths_alone(self, tmp_path):
        """Paths already in link syntax are not touched by fix."""
        repo = copy_fixture("autofix/unlinked-ref-already-linked", tmp_path)
        result = self._run_fix(repo)
        assert result.returncode == 0

        fixed = (repo / "CLAUDE.md").read_text()
        assert fixed.count("[docs/guide.md](docs/guide.md)") == 2
        assert "[[docs/guide.md]" not in fixed

    def test_fix_preserves_line_count(self, tmp_path):
        """Autofix must not add or remove lines — line numbers stay stable."""
        repo = copy_fixture("autofix/unlinked-ref-mixed", tmp_path)
        original = (repo / "CLAUDE.md").read_text()
        original_line_count = len(original.splitlines())

        self._run_fix(repo)
        fixed = (repo / "CLAUDE.md").read_text()
        fixed_line_count = len(fixed.splitlines())

        assert fixed_line_count == original_line_count


# ── SAFE Autofix Idempotency Suite ──────────────────────────────


def _discover_safe_autofix_rule_ids() -> Set[str]:
    """Auto-discover all rules that produce SAFE-confidence autofixes."""
    from skillsaw.rules.builtin import BUILTIN_RULES
    from skillsaw.rule import AutofixConfidence

    safe_ids: Set[str] = set()
    for rule_class in BUILTIN_RULES:
        instance = rule_class()
        if instance.autofix_confidence == AutofixConfidence.SAFE:
            safe_ids.add(instance.rule_id)
    return safe_ids


def _run_fix(path, *extra_args):
    args = [sys.executable, "-m", "skillsaw", "fix"]
    args.extend(extra_args)
    args.append(str(path))
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    assert (
        result.returncode == 0
    ), f"skillsaw fix failed with rc={result.returncode}: {result.stderr}"
    return result


def _snapshot_line_counts(repo: Path) -> Dict[str, int]:
    """Record line counts for every file in the repo."""
    counts: Dict[str, int] = {}
    for f in sorted(repo.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(repo))
        try:
            counts[rel] = len(f.read_text(encoding="utf-8").splitlines())
        except (UnicodeDecodeError, OSError):
            pass
    return counts


def _snapshot_contents(repo: Path) -> Dict[str, str]:
    """Record full content of every text file in the repo."""
    contents: Dict[str, str] = {}
    for f in sorted(repo.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(repo))
        try:
            contents[rel] = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            pass
    return contents


@pytest.mark.integration
class TestSafeAutofixIdempotency:
    """Comprehensive idempotency and correctness suite for all SAFE autofixes.

    Requirements (issue #177):
    - At least 100 violations across all rules that produce SAFE autofixes
    - Every SAFE autofix rule must have at least one violation
    - Running fix 11 times must produce identical content (idempotency)
    - In-place fixes must never change line counts
    - Re-lint after fix must show zero pre-existing violations for covered rules
    - No double-wrapping or other corruption bugs
    - Iterative fix_and_apply must converge (second pass finds nothing)
    """

    FIXTURE = "autofix/safe-idempotency"

    EXPECTED_SAFE_VIOLATIONS = {
        "agent-frontmatter": 3,
        "agentskill-name": 3,
        "agentskill-valid": 2,
        "command-frontmatter": 3,
        "content-unlinked-internal-reference": 22,
        "skill-frontmatter": 2,
    }

    def test_fixture_violation_counts(self, tmp_path):
        """Fixture must produce the exact expected SAFE violation counts."""
        repo = copy_fixture(self.FIXTURE, tmp_path)
        r = run_lint(repo)
        safe_rules = _discover_safe_autofix_rule_ids()
        by_rule: Dict[str, int] = {}
        for v in violations(r):
            if v["rule_id"] in safe_rules:
                by_rule[v["rule_id"]] = by_rule.get(v["rule_id"], 0) + 1
        assert by_rule == self.EXPECTED_SAFE_VIOLATIONS, (
            f"SAFE violation counts changed.\n"
            f"  Expected: {self.EXPECTED_SAFE_VIOLATIONS}\n"
            f"  Got:      {by_rule}"
        )

    def test_every_safe_rule_has_violations(self, tmp_path):
        """Every rule that produces SAFE autofixes must fire in the fixture."""
        repo = copy_fixture(self.FIXTURE, tmp_path)
        r = run_lint(repo)
        safe_rules = _discover_safe_autofix_rule_ids()
        fired = {v["rule_id"] for v in violations(r)} & safe_rules
        missing = safe_rules - fired
        assert not missing, (
            f"SAFE autofix rules without violations in fixture: {sorted(missing)}\n"
            f"Add fixture content to trigger these rules."
        )

    def test_fix_is_idempotent(self, tmp_path):
        """Running fix 11 times must produce byte-identical content after the first."""
        repo = copy_fixture(self.FIXTURE, tmp_path)
        _run_fix(repo)
        baseline = _snapshot_contents(repo)

        for i in range(10):
            _run_fix(repo)
            current = _snapshot_contents(repo)
            all_files = set(baseline.keys()) | set(current.keys())
            changed = {f for f in all_files if baseline.get(f) != current.get(f)}
            assert (
                not changed
            ), f"Files changed on fix iteration {i + 2} (not idempotent): {sorted(changed)}"

    def test_line_preserving_fixes_keep_line_counts(self, tmp_path):
        """In-place fixes (name renames, link wrapping) must not change line counts.

        Frontmatter fixes inherently add lines.  The engine handles this via
        iterative re-linting (fix_and_apply).  This test only checks files
        whose fixes are expected to be line-preserving.
        """
        repo = copy_fixture(self.FIXTURE, tmp_path)
        before = _snapshot_line_counts(repo)

        _run_fix(repo)
        after = _snapshot_line_counts(repo)

        # Only check files that should NOT have line-count changes.
        # Frontmatter-modifying fixes (missing frontmatter, missing fields)
        # inherently add lines and are excluded.
        frontmatter_fix_patterns = {
            "no-fm-",
            "no-frontmatter/",
            "no-desc-",
            "no-name-",
            "missing-name/",
            ".skillsaw-renames.json",
        }
        changed: List[str] = []
        for f in sorted(set(before) | set(after)):
            if any(pat in f for pat in frontmatter_fix_patterns):
                continue
            b = before.get(f)
            a = after.get(f)
            if b != a:
                changed.append(f"{f}: {b} -> {a}")

        assert not changed, "Line-preserving fixes changed line counts:\n" + "\n".join(
            f"  {c}" for c in changed
        )

    def test_iterative_convergence(self, tmp_path):
        """fix_and_apply converges: dirty-file re-lint produces correct results.

        When a fix adds frontmatter (changing line counts), the engine must
        re-lint and apply follow-up fixes at the correct line numbers.
        Verify the end result is clean and idempotent after convergence.
        """
        repo = copy_fixture(self.FIXTURE, tmp_path)
        _run_fix(repo)
        after_first = _snapshot_contents(repo)

        # Second fix should find nothing — proving convergence
        result = _run_fix(repo)
        after_second = _snapshot_contents(repo)

        assert (
            after_first == after_second
        ), "fix_and_apply did not converge — second pass changed files"
        assert "No auto-fixable violations found" in result.stdout

    def test_relint_shows_zero_pre_existing_safe_violations(self, tmp_path):
        """After fix, none of the original SAFE-rule violations should remain.

        Fixes may introduce new violations (e.g. adding frontmatter with an
        empty description triggers agentskill-valid).  Those are expected and
        need LLM fixes — we only assert that the violations that existed
        BEFORE the fix are resolved.
        """
        repo = copy_fixture(self.FIXTURE, tmp_path)
        safe_rules = _discover_safe_autofix_rule_ids()

        # Capture pre-fix violations keyed by (rule_id, file_path, message)
        r_before = run_lint(repo)
        before_keys = {
            (v["rule_id"], v["file_path"], v["message"])
            for v in violations(r_before)
            if v["rule_id"] in safe_rules
        }

        _run_fix(repo)

        r_after = run_lint(repo)
        after_keys = {
            (v["rule_id"], v["file_path"], v["message"])
            for v in violations(r_after)
            if v["rule_id"] in safe_rules
        }

        unfixed = before_keys & after_keys
        assert (
            not unfixed
        ), f"Pre-existing SAFE violations remain after fix ({len(unfixed)}):\n" + "\n".join(
            f"  {k[0]} @ {k[1]}: {k[2][:80]}" for k in sorted(unfixed)[:10]
        )

    def test_no_double_wrapping(self, tmp_path):
        """Fix must not double-wrap already-linked paths (regression for #173)."""
        repo = copy_fixture(self.FIXTURE, tmp_path)
        _run_fix(repo)

        for md_file in repo.rglob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            rel = str(md_file.relative_to(repo))
            assert "[[" not in content or content.count("[[") == content.count(
                "]]"
            ), f"Possible double-wrapping in {rel}"
            assert "](/" not in content.replace(
                "](http", "SKIP"
            ), f"Unexpected absolute path in link in {rel}"

    def test_fix_content_is_reasonable(self, tmp_path):
        """Spot-check that fixes produce well-formed markdown."""
        repo = copy_fixture(self.FIXTURE, tmp_path)
        _run_fix(repo)

        claude_md = (repo / "CLAUDE.md").read_text(encoding="utf-8")
        assert "]()" not in claude_md, "Empty link target found"

        for skill_dir in (repo / "skills").iterdir():
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            content = skill_md.read_text(encoding="utf-8")
            assert content.startswith(
                "---\n"
            ), f"SKILL.md in {skill_dir.name} missing frontmatter delimiter"
            assert (
                "\n---\n" in content[4:]
            ), f"SKILL.md in {skill_dir.name} missing closing frontmatter delimiter"
            lines = content.splitlines()
            name_lines = [line for line in lines if line.startswith("name:")]
            assert (
                len(name_lines) == 1
            ), f"SKILL.md in {skill_dir.name} has {len(name_lines)} name: lines"
            name_val = name_lines[0].split(":", 1)[1].strip()
            assert (
                name_val == skill_dir.name
            ), f"SKILL.md name '{name_val}' does not match dir '{skill_dir.name}'"


@pytest.mark.integration
class TestRuleFilter:
    """Tests for --rule flag filtering."""

    FIXTURE = "autofix/safe-idempotency"

    def test_rule_flag_limits_to_specified_rules(self, tmp_path):
        repo = copy_fixture(self.FIXTURE, tmp_path)
        r = run_lint(repo, "--rule", "agentskill-name")
        vs = violations(r)
        rule_ids = {v["rule_id"] for v in vs}
        assert rule_ids == {"agentskill-name"}

    def test_rule_flag_multiple_rules(self, tmp_path):
        repo = copy_fixture(self.FIXTURE, tmp_path)
        r = run_lint(repo, "--rule", "agentskill-name", "--rule", "agentskill-valid")
        vs = violations(r)
        rule_ids = {v["rule_id"] for v in vs}
        assert rule_ids == {"agentskill-name", "agentskill-valid"}

    def test_rule_flag_enables_disabled_rule(self, tmp_path):
        """--rule overrides enabled: false in config."""
        repo = copy_fixture(self.FIXTURE, tmp_path)
        r_without = run_lint(repo)
        assert not any(v["rule_id"] == "agentskill-evals-required" for v in violations(r_without))

        r_with = run_lint(repo, "--rule", "agentskill-evals-required")
        vs = violations(r_with)
        assert len(vs) > 0
        assert all(v["rule_id"] == "agentskill-evals-required" for v in vs)

    def test_rule_flag_unknown_rule_errors(self, tmp_path):
        repo = copy_fixture(self.FIXTURE, tmp_path)
        r = run_lint(repo, "--rule", "no-such-rule")
        assert r["rc"] != 0
        assert "Unknown rule" in r["stderr"]
        assert "no-such-rule" in r["stderr"]

    def test_rule_flag_unknown_rule_errors_fix(self, tmp_path):
        repo = copy_fixture(self.FIXTURE, tmp_path)
        args = [sys.executable, "-m", "skillsaw", "fix", "--rule", "no-such-rule", str(repo)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        assert result.returncode != 0
        assert "Unknown rule" in result.stderr

    def test_dry_run_shows_diff_without_modifying(self, tmp_path):
        repo = copy_fixture(self.FIXTURE, tmp_path)
        skip = {".skillsaw-renames.json"}
        before = {p: p.read_text() for p in repo.rglob("*") if p.is_file() and p.name not in skip}
        args = [
            sys.executable,
            "-m",
            "skillsaw",
            "fix",
            "--dry-run",
            "--rule",
            "agentskill-name",
            str(repo),
        ]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "NO_COLOR": "1"},
        )
        assert result.returncode == 0
        assert "Would fix" in result.stdout
        assert "dry-run" in result.stdout
        assert "@@" in result.stdout
        after = {p: p.read_text() for p in repo.rglob("*") if p.is_file() and p.name not in skip}
        assert before == after

    def test_rule_flag_works_with_fix(self, tmp_path):
        repo = copy_fixture(self.FIXTURE, tmp_path)
        result = _run_fix(repo, "--rule", "agentskill-name")
        assert "agentskill-name" not in result.stdout or "Fixed" in result.stdout
        assert result.returncode == 0
