"""Tests for the example plugin's extension points."""

import shutil
from pathlib import Path

from skillsaw.context import RepositoryContext

from skillsaw_example_plugin.extensions import (
    ACME_REPO_TYPE,
    AcmeConfigBlock,
    AcmeConfigVersionRule,
    contribute_acme_config,
)

FIXTURE = Path(__file__).parent / "fixture"


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    return repo


def test_repo_type_detection(tmp_path):
    repo = make_repo(tmp_path)
    assert ACME_REPO_TYPE.detect(repo)
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not ACME_REPO_TYPE.detect(plain)


def test_contributor_attaches_config_block(tmp_path):
    repo = make_repo(tmp_path)
    context = RepositoryContext(repo)
    blocks = contribute_acme_config(context, None)
    assert len(blocks) == 1
    assert isinstance(blocks[0], AcmeConfigBlock)


def test_version_rule_fires_on_contributed_block(tmp_path):
    repo = make_repo(tmp_path)
    context = RepositoryContext(repo)
    # In a real run skillsaw registers the contributor automatically; tests
    # register it directly on the context the same way.
    context.plugin_tree_contributors.append(("example", contribute_acme_config))
    violations = AcmeConfigVersionRule().check(context)
    assert len(violations) == 1
    assert "version" in violations[0].message
    assert violations[0].file_path.name == "config.json"
