"""Cursor marketplace pluginRoot normalization and native discovery."""

import json

import pytest

from skillsaw.blocks import CursorCommandBlock, CursorRuleBlock
from skillsaw.context import RepositoryContext
from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture


@pytest.mark.parametrize(
    "prefix, source, relative",
    [
        ("plugins", "plugins/review", "plugins/review"),
        ("plugins/", "plugins/review", "plugins/review"),
        ("plugins", "review", "plugins/review"),
        ("plugins", "plugins", "plugins"),
        ("plugins", "plugins-other", "plugins/plugins-other"),
        # A leading "./" on either side names the same directory.
        ("plugins", "./plugins/review", "plugins/review"),
        ("./plugins", "plugins/review", "plugins/review"),
        ("./plugins/", "./plugins/review", "plugins/review"),
        ("./plugins", "./review", "plugins/review"),
        # A root-relative source still resolves when the composed path is absent.
        ("vendor", "plugins/review", "plugins/review"),
    ],
)
def test_cursor_catalog_prefixed_sources(tmp_path, prefix, source, relative):
    repo = copy_fixture("cursor-plugins/prefixed-sources", tmp_path)
    if relative == "plugins/plugins-other":
        (repo / "plugins/review").rename(repo / "plugins/plugins-other")
    catalog = repo / ".cursor-plugin/marketplace.json"
    data = json.loads(catalog.read_text())
    data["metadata"]["pluginRoot"] = prefix
    data["plugins"][0]["source"] = source
    catalog.write_text(json.dumps(data))

    result = run_cli(
        [
            "lint",
            repo,
            "--no-custom-rules",
            "--rule",
            "cursor-marketplace-json-valid",
            "--format",
            "json",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["violations"] == []
    context = RepositoryContext(repo)
    assert context.cursor_plugin_roots() == [repo / relative]
    if relative != "plugins":
        assert [block.path for block in context.lint_tree.find(CursorCommandBlock)] == [
            repo / relative / "commands/review.md"
        ]


def test_cursor_dot_prefixed_source_is_linted_and_discovered(tmp_path):
    """sinch/sinch-plugins writes "./plugins/x" beside pluginRoot "plugins"."""
    repo = copy_fixture("cursor-plugins/marketplace-pluginroot-dot", tmp_path)
    result = run_cli(["lint", repo, "--no-custom-rules", "--format", "json"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["violations"] == []
    context = RepositoryContext(repo)
    plugin = repo / "plugins/deploy-helper"
    assert context.cursor_plugin_roots() == [plugin]
    assert [block.path for block in context.lint_tree.find(CursorRuleBlock)] == [
        plugin / "rules/manifests.mdc"
    ]
