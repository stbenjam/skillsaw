"""Regression coverage for release-triggered documentation deploys."""

from pathlib import Path

import pytest
from ruamel.yaml import YAML


@pytest.fixture
def workflow():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/pages.yml"
    return YAML(typ="safe").load(path.read_text())


def test_release_dispatches_a_deploy_from_main(workflow):
    # The github-pages environment only deploys from main, and a release run's
    # ref is its tag, so a release must hand the deploy to a run on main.
    assert "release" in workflow["on"]
    assert "workflow_dispatch" in workflow["on"]

    redeploy = workflow["jobs"]["redeploy-on-main"]
    assert redeploy["if"] == "github.event_name == 'release'"
    assert redeploy["permissions"] == {"actions": "write"}
    (step,) = redeploy["steps"]
    assert step["run"].split() == [
        "gh",
        "workflow",
        "run",
        "pages.yml",
        "--repo",
        '"$GITHUB_REPOSITORY"',
        "--ref",
        "main",
    ]


def test_release_run_never_deploys_from_its_tag(workflow):
    jobs = workflow["jobs"]
    assert jobs["build"]["if"] == "github.event_name != 'release'"
    assert jobs["deploy"]["needs"] == "build"
    assert jobs["deploy"]["environment"]["name"] == "github-pages"
