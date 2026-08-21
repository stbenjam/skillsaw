"""Release metadata consistency checks."""

import re
import tomllib
from pathlib import Path

from skillsaw.utils import read_yaml_commented

REPO_ROOT = Path(__file__).parent.parent


def test_action_and_ci_docs_default_to_project_version():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    project_version = project["project"]["version"]
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
