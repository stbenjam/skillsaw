"""Tests for ``skillsaw port`` and the ``agent-plugin-required`` rule."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.port import normalize_name, plan_port, render_mcp

FIXTURES = Path(__file__).parent / "fixtures" / "port"


def copy_fixture(name: str, tmp_path: Path) -> Path:
    dst = tmp_path / name.replace("/", "_")
    shutil.copytree(FIXTURES / name, dst)
    return dst


def run_port(*args, timeout=60):
    return subprocess.run(
        [sys.executable, "-m", "skillsaw", "port", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ── Name normalization ──────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("release-notes", "release-notes"),
        ("acme.tools", "acme.tools"),
        ("My Plugin", "my-plugin"),
        ("Has--Double", "has-double"),
        ("-strip-", "strip"),
        ("UPPER_case", "upper-case"),
        ("", None),
        ("---", None),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


# ── MCP translation ─────────────────────────────────────────────


def test_render_mcp_translates_transports_and_placeholders():
    notes = []
    content = render_mcp(
        {
            "local": {
                "command": "${CLAUDE_PLUGIN_ROOT}/bin/server",
                "args": ["--data", "${CLAUDE_PLUGIN_ROOT}/data"],
                "env": {"MODE": "fast"},
            },
            "remote": {"type": "http", "url": "https://api.example.com/mcp"},
            "socket": {"type": "ws", "url": "wss://x.example.com"},
        },
        notes,
    )
    data = json.loads(content)
    assert data["$schema"].endswith("/mcp.schema.json")
    local = data["mcpServers"]["local"]
    assert local == {
        "type": "stdio",
        "command": "./bin/server",
        "args": ["--data", "${PLUGIN_ROOT}/data"],
        "env": {"MODE": "fast"},
    }
    assert data["mcpServers"]["remote"] == {
        "type": "streamable-http",
        "url": "https://api.example.com/mcp",
    }
    assert "socket" not in data["mcpServers"]
    assert any("'socket'" in n for n in notes)


def test_render_mcp_skips_reserved_env_and_unportable_commands():
    notes = []
    content = render_mcp(
        {
            "reserved": {"command": "server", "env": {"PLUGIN_ROOT": "/x"}},
            "shellish": {"command": "run --flag thing"},
        },
        notes,
    )
    assert content is None
    assert any("reserved" in n for n in notes)
    assert any("shellish" in n for n in notes)


# ── plan_port ───────────────────────────────────────────────────


def test_plan_refuses_foreign_plugin_json(tmp_path):
    repo = copy_fixture("conflicting", tmp_path)
    plan = plan_port(repo)
    assert plan.writes == {}
    assert "refusing to overwrite" in plan.skipped


def test_plan_merges_codex_manifest(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    plan = plan_port(repo / "plugins" / "issue-triage")
    assert plan.sources == ["codex"]
    manifest = json.loads(plan.writes["plugin.json"])
    assert manifest["name"] == "issue-triage"
    assert manifest["version"] == "0.9.0"


# ── CLI ─────────────────────────────────────────────────────────


def test_port_dry_run_writes_nothing(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    result = run_port("--dry-run", repo)
    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    assert not (repo / "plugins" / "release-notes" / "plugin.json").exists()
    assert not (repo / "plugins" / "issue-triage" / "plugin.json").exists()


def test_port_marketplace_recursively(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    result = run_port(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Converted 2 plugins to Agent Plugins v1" in result.stdout
    assert "Validation: ✓ passed" in result.stdout

    manifest = json.loads((repo / "plugins" / "release-notes" / "plugin.json").read_text())
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert manifest["name"] == "release-notes"
    assert manifest["license"] == "Apache-2.0"
    assert manifest["author"] == {"name": "Example Team", "email": "team@example.com"}

    mcp = json.loads((repo / "plugins" / "release-notes" / "mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"changelog", "tracker"}
    assert mcp["mcpServers"]["changelog"]["command"] == "./bin/changelog-server"

    # The Codex-only plugin ports too, without an mcp.json.
    assert (repo / "plugins" / "issue-triage" / "plugin.json").exists()
    assert not (repo / "plugins" / "issue-triage" / "mcp.json").exists()


def test_port_rerun_is_clean(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    assert run_port(repo).returncode == 0
    first = {
        p: (repo / p).read_text()
        for p in ("plugins/release-notes/plugin.json", "plugins/release-notes/mcp.json")
    }
    rerun = run_port(repo)
    assert rerun.returncode == 0, rerun.stdout
    assert "Nothing to port" in rerun.stdout
    for p, content in first.items():
        assert (repo / p).read_text() == content


def test_port_refuses_conflicting_manifest(tmp_path):
    repo = copy_fixture("conflicting", tmp_path)
    result = run_port(repo)
    assert result.returncode == 1
    assert "refusing to overwrite" in result.stdout
    assert json.loads((repo / "plugin.json").read_text()).get("note")


def test_ported_marketplace_lints_clean(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    assert run_port(repo).returncode == 0
    for plugin in ("release-notes", "issue-triage"):
        context = RepositoryContext(repo / "plugins" / plugin)
        linter = Linter(
            context,
            LinterConfig.default(),
            rule_ids={"agent-plugin-json-valid", "agent-plugin-mcp-valid"},
            no_plugins=True,
            no_custom_rules=True,
        )
        findings = [v for v in linter.run() if v.rule_id.startswith("agent-plugin-")]
        assert findings == [], plugin


def test_port_completes_mcp_for_already_ported_plugin(tmp_path):
    """A package with the portable manifest but no portable mcp.json still
    gets the MCP translation on a later run."""
    repo = copy_fixture("marketplace", tmp_path)
    assert run_port(repo).returncode == 0
    mcp_path = repo / "plugins" / "release-notes" / "mcp.json"
    original = mcp_path.read_text()
    mcp_path.unlink()
    rerun = run_port(repo)
    assert rerun.returncode == 0, rerun.stdout
    assert mcp_path.read_text() == original


def test_port_fails_when_any_plugin_conflicts(tmp_path):
    """A partial port still exits nonzero when a plugin was refused."""
    repo = copy_fixture("marketplace", tmp_path)
    foreign = repo / "plugins" / "issue-triage" / "plugin.json"
    foreign.write_text('{"name": "issue-triage", "note": "someone else\'s file"}\n')
    result = run_port(repo)
    assert result.returncode == 1
    assert "refused" in result.stdout
    # The portable plugin still ported; the foreign file survived.
    assert (repo / "plugins" / "release-notes" / "plugin.json").exists()
    assert "someone else" in foreign.read_text()


def test_port_writes_codex_catalog(tmp_path):
    """A multi-plugin port also emits the Codex marketplace catalog so
    catalog-driven clients can discover the ported packages."""
    repo = copy_fixture("marketplace", tmp_path)
    result = run_port(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "catalog → .agents/plugins/marketplace.json (2 entries)" in result.stdout

    catalog = json.loads((repo / ".agents" / "plugins" / "marketplace.json").read_text())
    assert catalog["name"] == "marketplace"
    by_name = {e["name"]: e for e in catalog["plugins"]}
    assert by_name["release-notes"]["source"] == {
        "source": "local",
        "path": "./plugins/release-notes",
    }
    assert by_name["release-notes"]["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    assert by_name["issue-triage"]["source"]["path"] == "./plugins/issue-triage"


def test_port_leaves_existing_codex_catalog_alone(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    catalog_path = repo / ".agents" / "plugins" / "marketplace.json"
    catalog_path.parent.mkdir(parents=True)
    original = '{"name": "hand-made", "plugins": []}\n'
    catalog_path.write_text(original)
    result = run_port(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "left untouched" in result.stdout
    assert catalog_path.read_text() == original


def test_port_marketplaces_none_skips_catalog(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    result = run_port("--marketplaces", "none", repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (repo / ".agents").exists()


def test_port_rejects_unknown_marketplace(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    result = run_port("--marketplaces", "gemini", repo)
    assert result.returncode == 1
    assert "unknown --marketplaces" in result.stderr


# ── agent-plugin-required rule ──────────────────────────────────


def _run_rule(repo: Path, config: Optional[LinterConfig] = None):
    config = config or LinterConfig.default()
    config.rules.setdefault("agent-plugin-required", {})["enabled"] = True
    context = RepositoryContext(repo)
    linter = Linter(context, config=config, no_plugins=True, no_custom_rules=True)
    return linter, [v for v in linter.run() if v.rule_id == "agent-plugin-required"]


def test_rule_flags_missing_portable_manifests(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    _linter, violations = _run_rule(repo)
    assert len(violations) == 2
    assert all("not available as an Agent Plugins" in v.message for v in violations)
    assert all(v.fixable for v in violations)


def test_rule_fix_creates_portable_manifests(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    linter, _violations = _run_rule(repo)
    # The fix is SAFE: a plain `skillsaw fix` applies it.
    applied, _suggested = linter.fix_and_apply()
    assert applied
    assert (repo / "plugins" / "release-notes" / "plugin.json").exists()
    assert (repo / "plugins" / "release-notes" / "mcp.json").exists()
    # Re-check: the rule is satisfied after its own fix. (Drop the process-
    # level read cache first — a fresh CLI run wouldn't have one.)
    from skillsaw.rules.builtin.utils import invalidate_read_caches

    invalidate_read_caches()
    _linter, violations = _run_rule(repo)
    assert violations == []


def test_rule_flags_metadata_drift(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    assert run_port(repo).returncode == 0
    portable = repo / "plugins" / "release-notes" / "plugin.json"
    data = json.loads(portable.read_text())
    data["version"] = "9.9.9"
    portable.write_text(json.dumps(data, indent=2) + "\n")
    _linter, violations = _run_rule(repo)
    assert any("'version' differs" in v.message for v in violations)


def test_rule_flags_missing_portable_mcp(tmp_path):
    repo = copy_fixture("marketplace", tmp_path)
    assert run_port(repo).returncode == 0
    (repo / "plugins" / "release-notes" / "mcp.json").unlink()
    _linter, violations = _run_rule(repo)
    assert any("no portable" in v.message for v in violations)
    fixables = [v for v in violations if "no portable" in v.message]
    assert all(v.fixable for v in fixables)
