"""``grok-plugin-structure`` — whether Grok installs the directory at all.

The component set is the measured one, not the documented one:
``grok plugin install`` accepts a manifest-less directory holding
``skills/``, ``agents/``, ``hooks/hooks.json`` or ``.mcp.json``, and refuses
one holding only ``commands/`` or only ``.lsp.json`` with "no plugins found
in the source" — even though both are documented components and both load
once the directory is already installed.
"""

from __future__ import annotations

import json

import pytest

from skillsaw.context import RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokPluginStructureRule

from tests.grok._helpers import (
    HOOKS_JSON,
    at,
    copy_fixture,
    local_catalog,
    messages,
    run_rule,
    write_catalog,
    write_plugin,
    write_repo,
)

SKILL = (
    "---\nname: tide-window\ndescription: Find the low-tide windows long enough for a "
    "shoreline survey. Use when planning field work.\n---\n\n# Window\n\nAsk for the "
    "station id, then report each window.\n"
)
AGENT = (
    "---\nname: berth-reviewer\ndescription: Use when reviewing a berth allocation "
    "change.\n---\n\n# Berth reviewer\n\nReport each vessel with no berth.\n"
)
COMMAND = "---\ndescription: Draft the berth handover note\n---\n\n# Handover\n\nList the berths.\n"
SERVERS = json.dumps({"mcpServers": {"tides": {"type": "http", "url": "https://t.example/mcp"}}})


def catalog_repo(temp_dir, name: str, files):
    """A marketplace whose one entry is a manifest-less ``plugins/almanac``."""
    repo = write_repo(temp_dir / name)
    write_catalog(repo, local_catalog("./plugins/almanac"))
    plugin = repo / "plugins" / "almanac"
    plugin.mkdir(parents=True)
    for relative_path, body in files.items():
        target = plugin / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return repo


def check(repo, config=None):
    return run_rule(GrokPluginStructureRule, repo, config)


@pytest.fixture
def broken(tmp_path):
    return copy_fixture("grok/marketplace-broken", tmp_path)


# ── Nothing Grok would install ───────────────────────────────────


def test_a_commands_only_directory_is_one_finding(broken) -> None:
    found = at(check(broken), Severity.WARNING)

    assert len(found) == 1
    assert "Grok installs nothing from 'berth-notes/'" in found[0]
    assert "hooks/hooks.json or .mcp.json" in found[0]


@pytest.mark.parametrize(
    "files",
    [
        pytest.param({"README.md": "# almanac\n\nNothing here yet.\n"}, id="readme-only"),
        pytest.param({"commands/tide.md": COMMAND}, id="commands-only"),
        pytest.param({".lsp.json": "{}"}, id="lsp-only"),
        pytest.param({"skills/tide-window/notes.md": "# Notes\n"}, id="skills-without-skill-md"),
    ],
)
def test_directories_the_installer_refuses_warn(temp_dir, files) -> None:
    repo = catalog_repo(temp_dir, "refused-" + next(iter(files)).replace("/", "-"), files)

    assert any("Grok installs nothing" in message for message in at(check(repo), Severity.WARNING))


# ── What makes a manifest-less directory installable ─────────────


@pytest.mark.parametrize(
    "files",
    [
        pytest.param({"skills/tide-window/SKILL.md": SKILL}, id="skills"),
        pytest.param({"agents/berth-reviewer.md": AGENT}, id="agents"),
        pytest.param({"hooks/hooks.json": HOOKS_JSON}, id="hooks"),
        pytest.param({".mcp.json": SERVERS}, id="mcp"),
    ],
)
def test_an_installable_directory_is_only_the_naming_finding(temp_dir, files) -> None:
    repo = catalog_repo(temp_dir, "installable-" + next(iter(files))[:6], files)

    found = check(repo)

    assert at(found, Severity.WARNING) == []
    assert any("installs it as 'almanac-<hash>'" in message for message in messages(found))


def test_the_synthesized_name_finding_is_info(broken) -> None:
    found = at(check(broken), Severity.INFO)

    assert len(found) == 1
    assert "'current-log/' has no manifest" in found[0]


def test_a_manifest_settles_both_findings(temp_dir) -> None:
    repo = write_repo(temp_dir / "with-manifest")
    write_catalog(repo, local_catalog("./plugins/almanac"))
    write_plugin(repo / "plugins" / "almanac", {"name": "almanac", "version": "1.0.0"})

    assert check(repo) == []


def test_an_unresolvable_catalog_source_reports_nothing(temp_dir) -> None:
    """One defect, one finding: the catalog rule names the entry that
    declared a directory this repository does not have."""
    repo = write_repo(temp_dir / "unresolvable")
    write_catalog(repo, local_catalog("./plugins/does-not-exist"))

    assert check(repo) == []


def test_the_clean_fixtures_report_nothing(tmp_path) -> None:
    assert check(copy_fixture("grok/marketplace-clean", tmp_path)) == []
    assert check(copy_fixture("grok/plugin-clean", tmp_path)) == []
    assert check(copy_fixture("grok/plugin-declarations", tmp_path)) == []
    assert check(copy_fixture("grok/dual-manifest", tmp_path)) == []


# ── A directory no catalog addresses ─────────────────────────────


def test_a_directory_no_catalog_names_gets_no_synthesized_name_finding(temp_dir) -> None:
    """The INFO is about a name the catalog asks for and Grok does not
    provide. With no catalog there is no name to ask for: a plugin installed
    from a path is addressed by that path."""
    repo = write_repo(temp_dir / "unaddressed")
    (repo / "skills" / "tide-window").mkdir(parents=True)
    (repo / "skills" / "tide-window" / "SKILL.md").write_text(SKILL, encoding="utf-8")

    assert run_rule(GrokPluginStructureRule, repo, None, {RepositoryType.GROK_PLUGIN}) == []


def test_a_forced_type_still_reports_a_directory_grok_installs_nothing_from(temp_dir) -> None:
    """The forced seed is the whole point of ``--type grok-plugin``: without
    a node the check the operator asked for never runs."""
    repo = write_repo(temp_dir / "forced-empty")

    found = run_rule(GrokPluginStructureRule, repo, None, {RepositoryType.GROK_PLUGIN})

    assert [v.severity for v in found] == [Severity.WARNING]
    assert "Grok installs nothing from" in found[0].message
