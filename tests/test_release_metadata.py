"""Release metadata consistency checks."""

import re
from pathlib import Path

from skillsaw.utils import read_yaml_commented

REPO_ROOT = Path(__file__).parent.parent


def test_action_and_ci_docs_default_to_project_version():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    project_match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert project_match is not None, "pyproject.toml has no project version"
    project_version = project_match.group(1)
    action, error, _error_line = read_yaml_commented(REPO_ROOT / "action.yml")
    assert error is None
    action_version = action["inputs"]["version"]["default"]

    ci_docs = (REPO_ROOT / "docs" / "ci.md").read_text()
    documented = re.search(
        r"^\| `version` \| Specific skillsaw version to install \| `([^`]+)` \|$",
        ci_docs,
        re.MULTILINE,
    )

    assert documented is not None, "docs/ci.md has no action version input row"
    assert action_version == project_version
    assert documented.group(1) == project_version
