"""Tests for the .pre-commit-hooks.yaml manifest.

Validates the hook definition offline: structure, consistency with the
console scripts declared in pyproject.toml, and the repo-level invocation
contract. Running pre-commit itself requires network access (it builds an
isolated venv), so end-to-end verification is done with `pre-commit try-repo .`
manually or in CI.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
MANIFEST = REPO_ROOT / ".pre-commit-hooks.yaml"


@pytest.fixture(scope="module")
def hooks():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def skillsaw_hook(hooks):
    by_id = {h["id"]: h for h in hooks}
    return by_id["skillsaw"]


def test_manifest_is_a_list_of_hooks(hooks):
    assert isinstance(hooks, list)
    assert len(hooks) >= 1
    for hook in hooks:
        for required in ("id", "name", "entry", "language"):
            assert required in hook, f"hook {hook.get('id')} missing {required!r}"


def test_skillsaw_hook_contract(skillsaw_hook):
    assert skillsaw_hook["language"] == "python"
    # Repo-level linter: must not receive staged filenames as arguments
    assert skillsaw_hook["pass_filenames"] is False
    # Codex manifests may declare components at arbitrary paths, so any
    # filename filter could skip a component change or asset deletion.
    assert "files" not in skillsaw_hook
    assert skillsaw_hook["always_run"] is True
    # The entry must invoke a console script declared in pyproject.toml
    entry_cmd = skillsaw_hook["entry"].split()[0]
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(
        rf"^{re.escape(entry_cmd)}\s*=", pyproject, re.MULTILINE
    ), f"entry {entry_cmd!r} is not a [project.scripts] console script"
