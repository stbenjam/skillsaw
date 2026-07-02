"""
End-to-end tests for rule plugins.

These run the real CLI in a subprocess with a plugin *distribution* fixture
on PYTHONPATH — a package directory plus a ``.dist-info`` with an
``entry_points.txt``, which is exactly what ``pip install`` produces. That
exercises the same importlib.metadata discovery path as a published plugin,
without touching the test environment's site-packages.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PLUGIN_DIST = FIXTURES / "plugin-dist"
BROKEN_DIST = FIXTURES / "plugin-dist-broken"


def copy_fixture(name, tmp_path):
    src = FIXTURES / name
    dst = tmp_path / name.replace("/", "_")
    shutil.copytree(src, dst)
    return dst


def run_cli(*args, dists=(PLUGIN_DIST,), fmt=None, timeout=60, path_prepend=None, cwd=None):
    cmd = [sys.executable, "-m", "skillsaw", *args]
    if fmt:
        cmd.extend(["--format", fmt])
    env = dict(os.environ)
    pythonpath = os.pathsep.join(str(d) for d in dists)
    if env.get("PYTHONPATH"):
        pythonpath = pythonpath + os.pathsep + env["PYTHONPATH"]
    env["PYTHONPATH"] = pythonpath
    if path_prepend is not None:
        env["PATH"] = str(path_prepend) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)
    output = None
    if fmt == "json" and result.stdout.strip():
        output = json.loads(result.stdout)
    return {
        "rc": result.returncode,
        "out": output,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def plugin_violations(r, rule_id="no-wip-markers"):
    return [v for v in r["out"]["violations"] if v["rule_id"] == rule_id]


def test_lint_discovers_plugin_rule(tmp_path):
    repo = copy_fixture("plugin-target", tmp_path)
    r = run_cli("lint", str(repo), fmt="json")
    fired = plugin_violations(r)
    assert len(fired) == 1, r["stdout"] + r["stderr"]
    v = fired[0]
    assert v["severity"] == "warning"
    assert v["source"] == "plugin:no-wip"
    assert v["file_path"].endswith("CLAUDE.md")
    assert v["line"] == 17


def test_no_plugins_flag_skips_plugin_rules(tmp_path):
    repo = copy_fixture("plugin-target", tmp_path)
    r = run_cli("lint", "--no-plugins", str(repo), fmt="json")
    assert plugin_violations(r) == []


def test_config_can_disable_plugin(tmp_path):
    repo = copy_fixture("plugin-target", tmp_path)
    (repo / ".skillsaw.yaml").write_text(
        'version: "1.0"\nplugins:\n  disable: [no-wip]\n', encoding="utf-8"
    )
    r = run_cli("lint", str(repo), fmt="json")
    assert plugin_violations(r) == []


def test_config_can_configure_plugin_rule(tmp_path):
    repo = copy_fixture("plugin-target", tmp_path)
    (repo / ".skillsaw.yaml").write_text(
        'version: "1.0"\n'
        "rules:\n"
        "  no-wip-markers:\n"
        "    severity: error\n"
        '    markers: ["WIP:", "TBD:"]\n',
        encoding="utf-8",
    )
    (repo / "CLAUDE.md").write_text(
        (repo / "CLAUDE.md").read_text(encoding="utf-8") + "\nTBD: describe rollbacks.\n",
        encoding="utf-8",
    )
    r = run_cli("lint", str(repo), fmt="json")
    fired = plugin_violations(r)
    assert len(fired) == 2
    assert all(v["severity"] == "error" for v in fired)
    assert r["rc"] == 1  # plugin rule escalated to error affects exit code


def test_plugin_autofix_is_scoped_and_idempotent(tmp_path):
    repo = copy_fixture("plugin-target", tmp_path)
    claude_md = repo / "CLAUDE.md"
    original = claude_md.read_text(encoding="utf-8")
    original_lines = original.splitlines()

    r = run_cli("fix", "--rule", "no-wip-markers", str(repo))
    assert r["rc"] == 0, r["stdout"] + r["stderr"]
    assert "Removed work-in-progress marker" in r["stdout"]

    fixed = claude_md.read_text(encoding="utf-8")
    assert "WIP:" not in fixed
    # Only the marker line was removed; everything else is untouched.
    assert fixed.splitlines() == [ln for ln in original_lines if "WIP:" not in ln]

    # Idempotent: a second fix run changes nothing.
    r2 = run_cli("fix", "--rule", "no-wip-markers", str(repo))
    assert r2["rc"] == 0
    assert claude_md.read_text(encoding="utf-8") == fixed

    # Re-lint: no remaining violations for the plugin rule.
    r3 = run_cli("lint", str(repo), fmt="json")
    assert plugin_violations(r3) == []


def test_broken_plugin_reports_error_but_lint_completes(tmp_path):
    repo = copy_fixture("plugin-target", tmp_path)
    r = run_cli("lint", str(repo), dists=(PLUGIN_DIST, BROKEN_DIST), fmt="json")
    errors = [v for v in r["out"]["violations"] if v["rule_id"] == "plugin-load-error"]
    assert len(errors) == 1
    assert "broken" in errors[0]["message"]
    assert r["rc"] == 1
    # The healthy plugin still ran alongside the broken one.
    assert len(plugin_violations(r)) == 1


def test_plugins_subcommand_lists_plugins():
    r = run_cli("plugins")
    assert r["rc"] == 0, r["stdout"] + r["stderr"]
    assert "no-wip" in r["stdout"]
    assert "skillsaw-no-wip 0.2.0" in r["stdout"]
    assert "no-wip-markers" in r["stdout"]


def test_plugins_subcommand_reports_broken_plugin():
    r = run_cli("plugins", dists=(BROKEN_DIST,))
    assert r["rc"] == 1
    assert "ERROR" in r["stdout"]


def test_list_rules_includes_plugin_rules():
    r = run_cli("list-rules")
    assert r["rc"] == 0
    assert "Rules from plugin no-wip" in r["stdout"]
    assert "no-wip-markers" in r["stdout"]


def test_explain_plugin_rule(tmp_path):
    repo = copy_fixture("plugin-target", tmp_path)
    r = run_cli("explain", "no-wip-markers", str(repo))
    assert r["rc"] == 0, r["stdout"] + r["stderr"]
    assert "plugin: no-wip" in r["stdout"]
    assert "markers" in r["stdout"]  # config_schema is shown


# ---------------------------------------------------------------------------
# Plugin subcommands (skillsaw <name> -> skillsaw-<name>)
# ---------------------------------------------------------------------------

posix_only = pytest.mark.skipif(os.name != "posix", reason="shell-script fake executable")


def make_command(bin_dir, name):
    """Create a fake plugin executable that echoes its args and exits 7."""
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / name
    exe.write_text(f'#!/bin/sh\necho "{name} args: $@"\nexit 7\n', encoding="utf-8")
    exe.chmod(0o755)
    return exe


@posix_only
def test_plugin_subcommand_dispatch(tmp_path):
    bin_dir = tmp_path / "bin"
    make_command(bin_dir, "skillsaw-no-wip")
    r = run_cli("no-wip", "accept", "--flag", path_prepend=bin_dir)
    assert r["rc"] == 7, r["stdout"] + r["stderr"]
    assert "skillsaw-no-wip args: accept --flag" in r["stdout"]


@posix_only
def test_unregistered_executable_is_not_dispatched(tmp_path):
    """skillsaw-rogue on PATH without a registered plugin never runs."""
    bin_dir = tmp_path / "bin"
    make_command(bin_dir, "skillsaw-rogue")
    r = run_cli("rogue", path_prepend=bin_dir, cwd=tmp_path)
    assert r["rc"] == 1
    assert "Path not found: rogue" in r["stderr"]
    assert "args:" not in r["stdout"]


def test_registered_plugin_without_executable_falls_back_to_lint(tmp_path):
    r = run_cli("no-wip", cwd=tmp_path)
    assert r["rc"] == 1
    assert "Path not found: no-wip" in r["stderr"]


@posix_only
def test_plugin_command_wins_over_path_with_note(tmp_path):
    bin_dir = tmp_path / "bin"
    make_command(bin_dir, "skillsaw-no-wip")
    (tmp_path / "no-wip").mkdir()
    r = run_cli("no-wip", path_prepend=bin_dir, cwd=tmp_path)
    assert r["rc"] == 7
    assert "skillsaw-no-wip args:" in r["stdout"]
    assert "skillsaw lint no-wip" in r["stderr"]


@posix_only
def test_builtin_subcommand_wins_over_plugin_command(tmp_path):
    """A plugin named like a builtin cannot shadow it."""
    bin_dir = tmp_path / "bin"
    make_command(bin_dir, "skillsaw-list-rules")
    r = run_cli("list-rules", path_prepend=bin_dir)
    assert r["rc"] == 0
    assert "Available builtin rules" in r["stdout"]
    assert "args:" not in r["stdout"]


@posix_only
def test_plugins_subcommand_shows_command(tmp_path):
    bin_dir = tmp_path / "bin"
    make_command(bin_dir, "skillsaw-no-wip")
    r = run_cli("plugins", path_prepend=bin_dir)
    assert r["rc"] == 0
    assert "command: skillsaw no-wip" in r["stdout"]


# ---------------------------------------------------------------------------
# Extension points: plugin repo types and tree contributors
# ---------------------------------------------------------------------------


def test_plugin_repo_type_detected_and_reported(tmp_path):
    repo = copy_fixture("plugin-target-acme", tmp_path)
    r = run_cli("lint", str(repo), fmt="json")
    assert "acme" in r["out"]["stats"]["repo_types"], r["stdout"] + r["stderr"]


def test_scoped_plugin_rule_fires_on_contributed_block(tmp_path):
    """Detector -> repo type -> scoped rule -> contributor block, end to end."""
    repo = copy_fixture("plugin-target-acme", tmp_path)
    r = run_cli("lint", str(repo), fmt="json")
    fired = plugin_violations(r, rule_id="acme-config-version")
    assert len(fired) == 1, r["stdout"] + r["stderr"]
    v = fired[0]
    assert v["severity"] == "error"
    assert v["source"] == "plugin:no-wip"
    assert v["file_path"].endswith("config.json")
    assert r["rc"] == 1


def test_scoped_plugin_rule_inactive_without_repo_type(tmp_path):
    repo = copy_fixture("plugin-target", tmp_path)  # no ACME markers
    r = run_cli("lint", str(repo), fmt="json")
    assert plugin_violations(r, rule_id="acme-config-version") == []
    assert "acme" not in r["out"]["stats"]["repo_types"]


def test_content_rules_cover_plugin_content_paths(tmp_path):
    """Files matched by a repo type's content_paths get content-* rules."""
    repo = copy_fixture("plugin-target-acme", tmp_path)
    r = run_cli("lint", str(repo), fmt="json")
    weak = [
        v
        for v in r["out"]["violations"]
        if v["rule_id"] == "content-weak-language" and v["file_path"].endswith("ACME.md")
    ]
    assert weak, r["stdout"] + r["stderr"]


def test_tree_shows_plugin_contributed_nodes(tmp_path):
    repo = copy_fixture("plugin-target-acme", tmp_path)
    r = run_cli("tree", str(repo))
    assert r["rc"] == 0, r["stdout"] + r["stderr"]
    assert "ACME.md" in r["stdout"]
    assert "config.json" in r["stdout"]


def test_plugins_subcommand_lists_extensions():
    r = run_cli("plugins")
    assert r["rc"] == 0, r["stdout"] + r["stderr"]
    assert "acme — Repository configured for the ACME assistant" in r["stdout"]
    assert "tree contributors: contribute_acme_config" in r["stdout"]


def test_explain_shows_plugin_repo_type_scope(tmp_path):
    import re

    repo = copy_fixture("plugin-target-acme", tmp_path)
    r = run_cli("explain", "acme-config-version", str(repo))
    assert r["rc"] == 0, r["stdout"] + r["stderr"]
    plain = re.sub(r"\x1b\[[0-9;]*m", "", r["stdout"])
    assert "Applies to repo types: acme" in plain
    assert "detected repo type: acme" in plain
