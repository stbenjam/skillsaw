"""Native display SHA gating is separate from install pin normalization."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks import SkillBlock
from skillsaw.context import RepositoryContext
from tests.grok._helpers import copy_fixture, lint_json

SHA = "1f9d0c73a86b24e5107cad3f88b90250e6c147da"
CASES = [
    ("exact", False, SHA, SHA, True, None),
    ("case", False, SHA, SHA.upper(), False, "'sha' differs"),
    ("whitespace", False, SHA, " " + SHA, False, "'sha' differs"),
    ("catalog-only", False, SHA, None, False, "'sha' in the catalog only"),
    ("index-only", False, None, SHA, False, "'sha' in the index only"),
    ("empty-exact", False, "", "", True, None),
    ("empty-missing", False, "", None, False, "'sha' in the catalog only"),
    ("local", True, None, SHA, True, None),
    ("local-empty", True, None, "", True, None),
]


def configure(repo, local, catalog_sha, index_sha):
    path = repo / ".grok-plugin/marketplace.json"
    catalog = json.loads(path.read_text())
    if not local:
        source = {"url": "https://example.invalid/migration-tools.git"}
        if catalog_sha is not None:
            source["sha"] = catalog_sha
        catalog["plugins"][0]["source"] = source
    path.write_text(json.dumps(catalog))
    path = repo / ".grok-plugin/plugin-index.json"
    index = json.loads(path.read_text())
    if index_sha is not None:
        index["plugins"]["published-review"]["sha"] = index_sha
    path.write_text(json.dumps(index))


@pytest.mark.parametrize(
    "case,local,catalog_sha,index_sha,displayed,clause", CASES, ids=[row[0] for row in CASES]
)
def test_display_pin_comparison(tmp_path, case, local, catalog_sha, index_sha, displayed, clause):
    repo = copy_fixture("grok/index-keys", tmp_path)
    configure(repo, local, catalog_sha, index_sha)
    report = lint_json(
        repo,
        "--rule",
        "grok-marketplace-index-parity",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert report["stats"]["rules_run"] == ["grok-marketplace-index-parity"]
    findings = report["violations"]
    if clause is None:
        assert findings == []
    else:
        assert len(findings) == 1
        assert findings[0]["message"] == (
            "plugin-index.json disagrees with marketplace.json: " + clause + ": published-review"
        )
        assert findings[0]["severity"] == "warning"
    assert repo / "packages/catalog-canary/skills/review-catalog/SKILL.md" in {
        node.path for node in RepositoryContext(repo).lint_tree.find(SkillBlock)
    }


def test_ignoring_local_sha_keeps_component_drift(tmp_path):
    repo = copy_fixture("grok/index-keys", tmp_path)
    configure(repo, True, None, SHA)
    path = repo / ".grok-plugin/plugin-index.json"
    data = json.loads(path.read_text())
    data["plugins"]["published-review"]["components"]["skills"][0]["name"] = "retired"
    path.write_text(json.dumps(data))
    report = lint_json(
        repo,
        "--rule",
        "grok-marketplace-index-parity",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert len(report["violations"]) == 1
    message = report["violations"][0]["message"]
    assert "'sha'" not in message
    assert "skills only the index lists: published-review/retired" in message
    assert "skills only the plugin ships: published-review/review-migration" in message
