"""Typed catalog consumers share parsing and the existing invalidation boundary."""

import json

import pytest

from skillsaw.blocks import SkillBlock
from skillsaw.context import RepositoryContext
from skillsaw.formats import grok_catalog
from skillsaw.lint_target import GrokMarketplaceConfigNode
from skillsaw.linter import Linter
from skillsaw.utils import invalidate_read_caches
from tests.cli_runner import run_cli
from tests.grok._helpers import copy_fixture

CATALOG = ".grok-plugin/marketplace.json"
RULE = "grok-marketplace-json-valid"


@pytest.fixture
def parsed_catalogs(monkeypatch):
    original = json.loads
    calls = []

    def counted(content, *args, **kwargs):
        if kwargs.get("object_pairs_hook") is grok_catalog._Object:
            calls.append(content)
        return original(content, *args, **kwargs)

    monkeypatch.setattr(json, "loads", counted)
    return calls


def lint(repo):
    result = run_cli(
        [
            "lint",
            str(repo),
            "--format",
            "json",
            "--verbose",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
        ]
    )
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    assert RULE in report["stats"]["rules_run"]
    assert "grok-marketplace-index-parity" in report["stats"]["rules_run"]
    return result.returncode, report["violations"]


@pytest.mark.integration
def test_discovery_validity_and_parity_share_one_typed_parse(tmp_path, parsed_catalogs):
    repo = copy_fixture("grok/catalog-decoder", tmp_path)
    assert lint(repo) == (0, [])
    context = RepositoryContext(repo)
    assert [
        b.path.relative_to(repo).as_posix()
        for b in context.lint_tree.find(GrokMarketplaceConfigNode)
    ] == [CATALOG]
    assert sorted(
        b.path.relative_to(repo).as_posix() for b in context.lint_tree.find(SkillBlock)
    ) == [
        "packages/catalog-canary/skills/review-catalog/SKILL.md",
        "packages/migration-tools/skills/review-migration/SKILL.md",
        "plugins/fallback-canary/skills/review-fallback/SKILL.md",
    ]
    data, error = grok_catalog.read_catalog_json(path=repo / CATALOG)
    assert error is None
    assert data["owner"]["channel"] == "stable"
    assert [v for k, v in data["owner"].pairs if k == "channel"] == ["preview", "stable"]
    source = data["plugins"][0]["source"]
    assert [v for k, v in source.pairs if k == "path"] == [
        "./packages/retired",
        "./packages/migration-tools",
    ]
    assert len(parsed_catalogs) == 1


def test_keyword_paths_invalidate_only_the_changed_catalog(tmp_path, parsed_catalogs):
    one = copy_fixture("grok/catalog-decoder", tmp_path / "one") / CATALOG
    two = copy_fixture("grok/catalog-decoder", tmp_path / "two") / CATALOG
    first = grok_catalog.read_catalog_json(path=one)
    other = grok_catalog.read_catalog_json(path=two)
    assert len(parsed_catalogs) == 2
    one.write_text(one.read_text().replace('"name": "data-platform"', '"name": "changed-platform"'))
    invalidate_read_caches(one)
    changed = grok_catalog.read_catalog_json(path=one)
    assert changed[1] is None
    assert changed[0]["name"] == "changed-platform"
    assert first[0]["name"] == "data-platform"
    assert grok_catalog.read_catalog_json(path=two) is other
    assert other[0]["name"] == "data-platform"
    assert len(parsed_catalogs) == 3


def test_existing_linter_observes_an_explicitly_invalidated_catalog_edit(tmp_path):
    repo = copy_fixture("grok/catalog-decoder", tmp_path)
    path = repo / CATALOG
    linter = Linter(RepositoryContext(repo), no_custom_rules=True, no_plugins=True)
    assert linter.run() == []
    path.write_text(path.read_text().replace('"name": "data-platform"', '"name": 3'))
    invalidate_read_caches(path)
    found = linter.run()
    assert len(found) == 1
    assert (found[0].rule_id, found[0].file_path, found[0].severity.value) == (RULE, path, "error")
    assert found[0].message == "Marketplace catalog 'name' must be a string"


@pytest.mark.integration
@pytest.mark.parametrize(
    "invalid",
    [
        '{"name": "first", "name": "second", "plugins": []}',
        '\ufeff{"name": "bom", "plugins": []}',
        '{"name":',
    ],
)
def test_repeated_cli_runs_clear_cached_acceptance_and_refusal(tmp_path, parsed_catalogs, invalid):
    repo = copy_fixture("grok/catalog-decoder", tmp_path)
    path = repo / CATALOG
    original = path.read_bytes()
    assert lint(repo) == (0, [])
    assert len(parsed_catalogs) == 1
    path.write_text(invalid)
    code, findings = lint(repo)
    assert code == 1
    catalog_findings = [v for v in findings if v["rule_id"] == RULE]
    assert len(catalog_findings) == 1
    assert catalog_findings[0]["file_path"] == CATALOG
    assert catalog_findings[0]["severity"] == "error"
    # The fresh-process-equivalent CLI reset also evicts cached failures.
    path.write_bytes(original)
    before = len(parsed_catalogs)
    assert lint(repo) == (0, [])
    assert len(parsed_catalogs) == before + 1
