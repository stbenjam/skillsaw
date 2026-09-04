"""Release metadata consistency checks."""

import re
import shlex
import subprocess
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


_GIT_GREP_LINE = re.compile(r"^\s*[`(]*\$?\s*git grep .*$", re.MULTILINE)


def test_glob_pathspecs_in_skill_recipes_also_match_the_repo_root():
    """A `git grep … -- '**/NAME'` pathspec matches NAME only below a
    directory (git's fnmatch still needs the slash), so a recipe meant to
    find a root-level file has to list the bare name beside it."""
    checked = 0
    for path in sorted((REPO_ROOT / "skills").rglob("*.md")):
        for command in _GIT_GREP_LINE.findall(path.read_text()):
            if " -- " not in command:
                continue
            # Pathspecs end at the first pipe: a downstream `grep` pattern
            # must not satisfy the bare-name check by accident.
            pathspecs = shlex.split(command.split(" -- ", 1)[1].split("|", 1)[0])
            for nested in (spec[3:] for spec in pathspecs if spec.startswith("**/")):
                checked += 1
                assert (
                    nested in pathspecs
                ), f"{path.relative_to(REPO_ROOT)}: '**/{nested}' needs a bare '{nested}' too"
    assert checked >= 6, "the pathspec guard found no recipes to check"


_ROUTER_SCAN = re.compile(r"^git grep --untracked -lE '([^']+)'$", re.MULTILINE)

# One line per pin form the skill's references document. The router scan
# decides whether the pins reference is read at all, so a form it misses is a
# pin the skill never touches.
ROUTER_MUST_MATCH = [
    "FROM ghcr.io/stbenjam/skillsaw:0.19.0",
    "  image: ghcr.io/stbenjam/skillsaw:0.19.0",
    "  image: registry.example.com/mirror/stbenjam/skillsaw:0.19.0",
    "FROM ghcr.io/stbenjam/skillsaw@sha256:dead",
    "FROM ghcr.io/stbenjam/skillsaw",
    "  - repo: https://github.com/stbenjam/skillsaw",
    "  - uses: stbenjam/skillsaw@abc123 # v0.19.0",
    "  - uses: stbenjam/skillsaw/review@abc123",
    "SKILLSAW_VERSION := 0.19.0",
    "    - pip install skillsaw==0.20.0",
    "uvx skillsaw@0.19.0",
    "skillsaw >= 0.19.0",
    "skillsaw != 0.18.0",
    'skillsaw = { version = "0.19.0" }',
    'skillsaw = "^0.19.0"',
]
ROUTER_MUST_NOT_MATCH = [
    "acme-skillsaw==1.0.0",
    "python_skillsaw>=1",
    "example.com/o/skillsawtool:1.0",
    "skillsaw is a linter for agent context",
]


def test_the_router_pin_scan_matches_every_documented_pin_form():
    """The step-3 scan in SKILL.md gates the pins reference. Run the pattern
    it ships through `grep -E`, the engine the agent runs, against one line
    per documented pin form and a few near misses. The pattern is read from
    the skill, so this cannot go stale against it."""
    skill = (REPO_ROOT / "skills" / "skillsaw-update" / "SKILL.md").read_text()
    patterns = _ROUTER_SCAN.findall(skill)
    assert len(patterns) == 1, patterns

    def matches(line: str) -> bool:
        result = subprocess.run(
            ["grep", "-qE", patterns[0]], input=line + "\n", text=True, check=False
        )
        return result.returncode == 0

    for line in ROUTER_MUST_MATCH:
        assert matches(line), f"router scan misses: {line!r}"
    for line in ROUTER_MUST_NOT_MATCH:
        assert not matches(line), f"router scan over-matches: {line!r}"


def test_image_tags_in_skills_and_docs_carry_no_v():
    """The image is tagged `0.19.0`, never `v0.19.0` (docker.yml publishes
    `type=semver,pattern={{version}}`), so a `:v` tag in a recipe pulls
    nothing."""
    hits = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for root in ("skills", "docs")
        for path in sorted((REPO_ROOT / root).rglob("*.md"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "ghcr.io/stbenjam/skillsaw:v" in line
    ]
    assert hits == []
