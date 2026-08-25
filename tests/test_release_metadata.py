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


def test_documented_skillsaw_floor_is_installable():
    """Every `skillsaw>=X.Y[.Z]` floor in docs, skills, and examples must be
    one single value, at most the project version — main's version is the
    next release, so a floor above it is unsatisfiable at pip resolution
    for every scaffolded plugin. Disagreeing floors mean a partial update.
    scripts/bump-version.sh rewrites the floor alongside the other pins."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    project_match = re.search(r'^version = "(\d+)\.(\d+)\.(\d+)"$', pyproject, re.MULTILINE)
    assert project_match is not None
    project = tuple(int(g) for g in project_match.groups())

    floors = {}
    for base in ("docs", "skills", ".claude/skills", ".agents/skills", "examples"):
        root = REPO_ROOT / base
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in (".md", ".toml") or not path.is_file():
                continue
            for m in re.finditer(r"skillsaw>=(\d+)\.(\d+)(?:\.(\d+))?", path.read_text()):
                floor = tuple(int(g) for g in m.groups() if g is not None)
                floors.setdefault(floor, []).append(str(path.relative_to(REPO_ROOT)))

    assert floors, "expected at least one documented skillsaw>= floor"
    assert len(floors) == 1, f"floor sites disagree: {floors}"
    (floor,) = floors
    padded = floor + (0,) * (3 - len(floor))
    assert padded <= project, (
        f"documented floor {'.'.join(map(str, floor))} exceeds the project "
        f"version {'.'.join(map(str, project))} — no release can satisfy it "
        "until the version catches up"
    )
