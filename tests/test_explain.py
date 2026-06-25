"""
Tests for `skillsaw explain <rule-id>` and the rule documentation helpers.
"""

import os
import subprocess
import sys

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.rule_docs import load_rule_docs, rule_doc_url
from skillsaw.rules.builtin import BUILTIN_RULES


def run_explain(rule_id, *extra_args):
    """Run `skillsaw explain RULE [PATH...]`; extra_args are CLI arguments
    (typically the positional repository path)."""
    args = [sys.executable, "-m", "skillsaw", "explain", rule_id, *extra_args]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "NO_COLOR": "1"},
    )
    return result


# --- rule_docs helpers ---


def test_rule_doc_url():
    assert (
        rule_doc_url("content-weak-language") == "https://skillsaw.org/rules/content-weak-language/"
    )


def test_load_rule_docs_present():
    docs = load_rule_docs("content-weak-language")
    assert docs is not None
    assert "## Why" in docs
    assert "## Examples" in docs


def test_load_rule_docs_all_rules_covered():
    """Every builtin rule should have long-form docs with a How to fix section."""
    for rule_class in BUILTIN_RULES:
        rule = rule_class()
        docs = load_rule_docs(rule.rule_id)
        assert docs is not None, f"Missing docs for {rule.rule_id}"
        assert "## How to fix" in docs, f"Missing '## How to fix' in {rule.rule_id}"


def test_load_rule_docs_absent():
    assert load_rule_docs("no-such-rule") is None


# --- explain CLI ---


def test_explain_known_rule(temp_dir):
    result = run_explain("content-weak-language", str(temp_dir))
    assert result.returncode == 0
    assert "content-weak-language" in result.stdout
    assert "Detect hedging" in result.stdout
    assert "llm-fix: yes" in result.stdout
    assert "since 0.7.0" in result.stdout
    assert "https://skillsaw.org/rules/content-weak-language/" in result.stdout
    # Long-form docs are included
    assert "## Why" in result.stdout


def test_explain_shows_config_schema(temp_dir):
    result = run_explain("content-critical-position", str(temp_dir))
    assert result.returncode == 0
    assert "min-lines" in result.stdout
    assert "Minimum file length" in result.stdout


def test_explain_unknown_rule_suggests_close_match(temp_dir):
    result = run_explain("content-weak-langage", str(temp_dir))
    assert result.returncode == 1
    assert "Unknown rule" in result.stderr
    assert "content-weak-language" in result.stderr


def test_explain_shows_long_docs(temp_dir):
    result = run_explain("marketplace-json-valid", str(temp_dir))
    assert result.returncode == 0
    assert "marketplace-json-valid" in result.stdout
    assert "https://skillsaw.org/rules/marketplace-json-valid/" in result.stdout
    assert "## How to fix" in result.stdout


def test_explain_effective_disabled_by_config(temp_dir):
    (temp_dir / ".skillsaw.yaml").write_text(
        "version: '99.0.0'\n" "rules:\n" "  content-weak-language:\n" "    enabled: false\n"
    )
    result = run_explain("content-weak-language", str(temp_dir))
    assert result.returncode == 0
    assert "disabled" in result.stdout
    assert "enabled: false set in config" in result.stdout


def test_explain_effective_version_gate(temp_dir):
    (temp_dir / ".skillsaw.yaml").write_text("version: '0.1.0'\n")
    result = run_explain("hooks-dangerous", str(temp_dir))
    assert result.returncode == 0
    assert "config version 0.1.0 is older than the rule" in result.stdout


def test_explain_effective_repo_type_no_match(temp_dir):
    # Empty dir: marketplace-registration is auto + repo-type gated
    (temp_dir / ".skillsaw.yaml").write_text("version: '99.0.0'\n")
    result = run_explain("marketplace-registration", str(temp_dir))
    assert result.returncode == 0
    assert "no matching repo type or format detected" in result.stdout


def test_explain_nonexistent_path_fails(temp_dir):
    result = run_explain("content-weak-language", str(temp_dir / "does-not-exist"))
    assert result.returncode == 1
    assert "Path not found" in result.stderr


def test_explain_missing_config_file_fails(temp_dir):
    result = run_explain("content-weak-language", str(temp_dir), "-c", str(temp_dir / "nope.yaml"))
    assert result.returncode == 1
    assert "Config file not found" in result.stderr


def test_explain_effective_repo_type_match(valid_plugin):
    result = run_explain("plugin-json-required", str(valid_plugin))
    assert result.returncode == 0
    assert "enabled: auto — detected repo type:" in result.stdout
    assert "single-plugin" in result.stdout


# --- rule_enabled_reason stays consistent with is_rule_enabled ---


@pytest.mark.parametrize(
    "config_yaml",
    [
        "",
        "version: '0.1.0'\n",
        "version: '99.0.0'\n",
        "rules:\n  content-weak-language:\n    enabled: false\n",
        "rules:\n  command-sections:\n    severity: error\n",
    ],
)
def test_rule_enabled_reason_matches_is_rule_enabled(temp_dir, config_yaml):
    config_path = temp_dir / ".skillsaw.yaml"
    config_path.write_text(config_yaml)
    config = LinterConfig.from_file(config_path)
    context = RepositoryContext(temp_dir)

    for rule_class in BUILTIN_RULES:
        rule = rule_class()
        enabled = config.is_rule_enabled(
            rule.rule_id, context, rule.repo_types, rule.formats, since_version=rule.since
        )
        reason_enabled, reason = config.rule_enabled_reason(
            rule.rule_id, context, rule.repo_types, rule.formats, since_version=rule.since
        )
        assert enabled == reason_enabled, rule.rule_id
        assert reason, rule.rule_id
