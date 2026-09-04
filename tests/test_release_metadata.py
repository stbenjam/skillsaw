"""Release metadata consistency checks."""

import re
import shlex
import subprocess
from pathlib import Path

from skillsaw.utils import read_yaml_commented
from tests.cli_runner import run_cli

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


_GIT_GREP_LINE = re.compile(r"^\s*[`(]*\$?\s*(git grep [^`\n]*)", re.MULTILINE)
SKILL_DIR = REPO_ROOT / "skills" / "skillsaw-update"


def _grep_matches(pattern: str, line: str) -> bool:
    """Run *pattern* through `grep -E`, the engine the agent runs (Python's
    `re` has no `[[:alnum:]]`)."""
    result = subprocess.run(
        ["grep", "-qE", pattern], input=line + "\n", text=True, check=False, capture_output=True
    )
    # 1 is "no match"; anything above is grep refusing the pattern.
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


def _command_tokens(command: str) -> list:
    """The `git grep …` tokens up to a pipe: a pattern may itself hold `|`,
    so the command is tokenised before the pipe is looked for."""
    tokens = shlex.split(command)
    return tokens[: tokens.index("|")] if "|" in tokens else tokens


def _is_recipe(command: str) -> bool:
    """A harvested `git grep …` line is a recipe only when it carries a
    pattern; a backticked prose mention such as `git grep --untracked`
    does not, and running it would be a patternless `git grep`."""
    tokens = _command_tokens(command)
    return tokens[:2] == ["git", "grep"] and any(not t.startswith("-") for t in tokens[2:])


def _grep_pattern(command: str) -> str:
    """The pattern argument of a `git grep …` command line."""
    tokens = _command_tokens(command)
    pattern = next((token for token in tokens[2:] if not token.startswith("-")), None)
    assert pattern is not None, f"no pattern in {command!r}"
    return pattern


def test_glob_pathspecs_in_skill_recipes_also_match_the_repo_root():
    """A `git grep … -- '**/NAME'` pathspec matches NAME only below a
    directory (git's fnmatch still needs the slash), so a recipe meant to
    find a root-level file has to list the bare name beside it."""
    checked = 0
    for path in sorted((REPO_ROOT / "skills").rglob("*.md")):
        for command in _GIT_GREP_LINE.findall(path.read_text()):
            tokens = _command_tokens(command)
            if "--" not in tokens:
                continue
            # Pathspecs end at the pipe: a downstream `grep` pattern must
            # not satisfy the bare-name check by accident.
            pathspecs = tokens[tokens.index("--") + 1 :]
            for nested in (spec[3:] for spec in pathspecs if spec.startswith("**/")):
                checked += 1
                assert (
                    nested in pathspecs
                ), f"{path.relative_to(REPO_ROOT)}: '**/{nested}' needs a bare '{nested}' too"
    assert checked >= 6, f"the pathspec guard checked only {checked} '**/' pathspecs"


# One line per pin form the skill's references document. The router scan
# decides whether the pins reference is read at all, so a form it misses is a
# pin the skill never touches.
ROUTER_MUST_MATCH = [
    "FROM ghcr.io/stbenjam/skillsaw:0.19.0",
    "  image: ghcr.io/stbenjam/skillsaw:0.19.0",
    "  image: registry.example.com/mirror/stbenjam/skillsaw:0.19.0",
    "FROM ghcr.io/stbenjam/skillsaw@sha256:dead",
    "FROM ghcr.io/stbenjam/skillsaw",
    "  image: 'ghcr.io/stbenjam/skillsaw'",
    "  - repo: https://github.com/stbenjam/skillsaw",
    "  - uses: stbenjam/skillsaw@abc123 # v0.19.0",
    "  - uses: stbenjam/skillsaw/review@abc123",
    "SKILLSAW_VERSION := 0.19.0",
    "    - pip install skillsaw==0.20.0",
    "uvx skillsaw@0.19.0",
    "skillsaw >= 0.19.0",
    "skillsaw != 0.18.0",
    "skillsaw[dev]==0.19.0",
    "skillsaw ~= 0.19",
    "skillsaw===0.19.0",
    "skillsaw<0.21",
    "skillsaw==$SKILLSAW_VERSION",
    "skillsaw @ git+https://github.com/stbenjam/skillsaw.git@v0.19.0",
    'skillsaw = { version = "0.19.0" }',
    'skillsaw = "^0.19.0"',
    "skillsaw = '^0.19.0'",
    'name = "skillsaw"',
]
ROUTER_MUST_NOT_MATCH = [
    "acme-skillsaw==1.0.0",
    "python_skillsaw>=1",
    "example.com/o/skillsawtool:1.0",
    "skillsaw is a linter for agent context",
]


def _router_pattern() -> str:
    commands = [
        command
        for command in _GIT_GREP_LINE.findall((SKILL_DIR / "SKILL.md").read_text())
        if command.startswith("git grep --untracked -lE")
    ]
    assert len(commands) == 1, commands
    return _grep_pattern(commands[0])


def test_the_router_pin_scan_matches_every_documented_pin_form():
    """The step-3 scan in SKILL.md gates the pins reference. Run the pattern
    it ships against one line per documented pin form and a few near misses.
    The pattern is read from the skill, so this cannot go stale against it."""
    pattern = _router_pattern()
    for line in ROUTER_MUST_MATCH:
        assert _grep_matches(pattern, line), f"router scan misses: {line!r}"
    for line in ROUTER_MUST_NOT_MATCH:
        assert not _grep_matches(pattern, line), f"router scan over-matches: {line!r}"


# The same pin lines placed where a repository keeps them, so each recipe runs
# with its own pathspecs against a real git work tree. Near misses live in a
# file no recipe is scoped to and must surface nowhere.
PIN_FIXTURE = {
    ".github/workflows/lint.yml": [
        "  - uses: stbenjam/skillsaw@abc123 # v0.19.0",
        "    with:",
        "      version: 0.19.0",
        "  - uses: stbenjam/skillsaw/review@abc123",
    ],
    "action.yml": [
        "inputs:",
        "  version:",
        "    description: The skillsaw version to install",
        '    default: "0.19.0"',
    ],
    "Makefile": ["SKILLSAW_VERSION := 0.19.0", "\tuvx skillsaw@0.19.0"],
    ".pre-commit-config.yaml": ["  - repo: https://github.com/stbenjam/skillsaw"],
    "Dockerfile": [
        "FROM ghcr.io/stbenjam/skillsaw:0.19.0",
        "FROM ghcr.io/stbenjam/skillsaw@sha256:dead",
        "FROM ghcr.io/stbenjam/skillsaw",
        "RUN pip install skillsaw==0.20.0",
    ],
    ".gitlab-ci.yml": [
        "  image: ghcr.io/stbenjam/skillsaw:0.19.0",
        "  image: registry.example.com/mirror/stbenjam/skillsaw:0.19.0",
        "  image: 'ghcr.io/stbenjam/skillsaw'",
    ],
    "requirements.txt": [
        "skillsaw >= 0.19.0",
        "skillsaw != 0.18.0",
        "skillsaw[dev]==0.19.0",
        "skillsaw ~= 0.19",
        "skillsaw===0.19.0",
        "skillsaw<0.21",
        "skillsaw==$SKILLSAW_VERSION",
        "skillsaw @ git+https://github.com/stbenjam/skillsaw.git@v0.19.0",
    ],
    "pyproject.toml": [
        'skillsaw = { version = "0.19.0" }',
        'skillsaw = "^0.19.0"',
        "skillsaw = '^0.19.0'",
    ],
    "uv.lock": ['name = "skillsaw"'],
    "docs/notes.md": ROUTER_MUST_NOT_MATCH,
}
# Lines a recipe must surface, where that is not every line of the file: the
# action-metadata recipe keeps only the `default:` line, and the `inputs:`
# scaffolding around it is not a pin.
PIN_EXPECTED = {
    "action.yml": ['    default: "0.19.0"'],
    "docs/notes.md": [],
}


def test_the_pins_recipes_together_find_every_documented_pin_form(tmp_path):
    """Each recipe in the pins reference owns one surface; run every one, with
    its own pathspecs, against a git work tree holding one pin per documented
    form, and require the union to reach each pin and none of the near misses.
    Commands are read from the reference itself."""
    for name, lines in PIN_FIXTURE.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    commands = [
        command
        for command in _GIT_GREP_LINE.findall((SKILL_DIR / "references" / "03-pins.md").read_text())
        if _is_recipe(command)
    ]
    # Actions, action metadata, Makefile, pre-commit, container, PyPI, the
    # pyproject mapping sweep and the lockfile lookup: a dropped recipe must
    # fail here rather than pass unnoticed.
    assert len(commands) == 8, commands
    found = ""
    for command in commands:
        result = subprocess.run(
            ["bash", "-c", command], cwd=tmp_path, capture_output=True, text=True, check=False
        )
        # 1 is "no match"; anything above is git grep refusing the command.
        assert result.returncode in (0, 1), (command, result.stderr)
        found += result.stdout
    for name, lines in PIN_FIXTURE.items():
        expected = PIN_EXPECTED.get(name, lines)
        for index, line in enumerate(lines, 1):
            # Anchored on `git grep -n`'s own output shape (`file:line:text`,
            # or `file-line-text` for a context line), so a shorter pin is
            # never credited by a longer line above it and a line from
            # another file never stands in.
            hit = f"{name}:{index}:{line}" in found or f"{name}-{index}-{line}" in found
            if line in expected:
                assert hit, f"no recipe finds: {name}:{index}:{line!r}"
            else:
                assert not hit, f"a recipe over-matches: {name}:{index}:{line!r}"


def test_image_tags_in_skills_and_docs_carry_no_v():
    """The image is tagged `0.19.0`, never `v0.19.0` (docker.yml publishes
    `type=semver,pattern={{version}}`), so a `:v` tag in a recipe pulls
    nothing, at ghcr.io or at a mirror."""
    files = [
        path
        for root in ("skills", "docs", "examples", "README.md")
        for path in (sorted((REPO_ROOT / root).rglob("*.md")) or [REPO_ROOT / root])
        if path.is_file()
    ]
    assert len(files) >= 50, "the image-tag guard walked almost nothing"
    hits = [
        f"{path.relative_to(REPO_ROOT)}:{number}"
        for path in files
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if "stbenjam/skillsaw:v" in line
    ]
    assert hits == []


def test_the_cli_strings_the_update_skill_parses(tmp_path):
    """The update skill reads three things the CLI prints: `Using config:
    <path>` from `lint -v` (absent when no config file exists), the
    two-space-indented rule IDs of `list-rules`, and `skillsaw N.N.N` from
    `--version`."""
    (tmp_path / "AGENTS.md").write_text("# Notes\n\nKeep changes small.\n")
    without = run_cli(["lint", "-v", str(tmp_path)])
    assert "Using config: " not in without.stdout, without.stdout

    (tmp_path / ".skillsaw.yaml").write_text('version: "99.0.0"\n')
    result = run_cli(["lint", "-v", str(tmp_path)])
    using = [line for line in result.stdout.splitlines() if line.startswith("Using config: ")]
    assert using and using[0].endswith(".skillsaw.yaml"), result.stdout

    listing = run_cli(["list-rules"])
    ids = re.findall(r"^  ([a-z][a-z0-9-]*)", listing.stdout, re.MULTILINE)
    assert len(ids) >= 50 and "content-description-routing" in ids, listing.stdout[:400]

    version = run_cli(["--version"])
    assert re.fullmatch(r"skillsaw \d+\.\d+\.\d+\s*", version.stdout), version.stdout


def test_the_git_tag_fallback_pipeline_returns_the_newest_release():
    """The `ls-remote` fallback in both skills filters its listing through a
    `grep | tail | sed` pipeline that must drop the floating `v0`, a
    prerelease and any peeled `^{}` line and print a bare `N.N.N`. Run the
    shipped pipeline over a listing in `--sort=v:refname` order."""
    listing = (
        "aaaa\trefs/tags/v0\n"
        "bbbb\trefs/tags/v0.19.0\n"
        "cccc\trefs/tags/v0.20.0\n"
        "dddd\trefs/tags/v0.21.0-rc1\n"
    )
    for reference in (
        SKILL_DIR / "references" / "01-versions.md",
        REPO_ROOT / "skills" / "skillsaw-onboard" / "references" / "09-makefile.md",
    ):
        commands = re.findall(r"^git ls-remote .*$", reference.read_text(), re.MULTILINE)
        assert len(commands) == 1, (reference, commands)
        # `tail -1` is only right because the listing arrives version-sorted.
        assert "--sort='v:refname'" in commands[0], commands[0]
        pipeline = commands[0].split("|", 1)[1]
        result = subprocess.run(
            ["bash", "-c", pipeline], input=listing, text=True, capture_output=True, check=True
        )
        assert result.stdout.strip() == "0.20.0", (reference, result.stdout)
