"""Tests for Vercel skills CLI project lockfiles."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from skillsaw.blocks import SkillsLockBlock
from skillsaw.config import LinterConfig
from skillsaw.context import HAS_SKILLS_LOCK, RepositoryContext
from skillsaw.formats import skills_lock
from skillsaw.lint_target import SkillNode
from skillsaw.linter import Linter
from skillsaw.rule import Severity
from skillsaw.rules.builtin.skills_lock import SkillsLockValidRule
from tests.cli_runner import run_cli

FIXTURES = Path(__file__).parent / "fixtures"
HASH = "0123456789abcdef" * 4


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name.replace("/", "_")
    shutil.copytree(FIXTURES / name, destination)
    return destination


def _write_lock(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _entry(**overrides: object) -> dict:
    entry = {
        "source": "vercel-labs/skills",
        "sourceType": "github",
        "computedHash": HASH,
    }
    entry.update(overrides)
    return entry


def _messages(repo: Path, config: dict | None = None) -> list[str]:
    rule = SkillsLockValidRule(config)
    return [violation.message for violation in rule.check(RepositoryContext(repo))]


def test_rule_defaults_to_auto_and_error() -> None:
    config = LinterConfig.default().get_rule_config("skills-lock-valid")
    assert config["enabled"] == "auto"
    assert SkillsLockValidRule().default_severity() == Severity.ERROR


def test_valid_root_and_nested_lockfiles_pass(tmp_path: Path) -> None:
    repo = _copy_fixture("skills-lock/valid", tmp_path)
    context = RepositoryContext(repo)

    assert HAS_SKILLS_LOCK in context.detected_formats
    blocks = context.lint_tree.find(SkillsLockBlock)
    assert [block.path.relative_to(repo) for block in blocks] == [
        Path("packages/web/skills-lock.json"),
        Path("skills-lock.json"),
    ]
    assert blocks[0].tree_label() == "skills-lock.json (skills lockfile)"
    assert SkillsLockValidRule().check(context) == []


def test_rule_auto_enables_for_an_unknown_repository(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {"version": 1, "skills": {"broken": _entry(computedHash="bad")}},
    )

    violations = Linter(RepositoryContext(tmp_path), LinterConfig.default()).run()

    lock_violations = [v for v in violations if v.rule_id == "skills-lock-valid"]
    assert len(lock_violations) == 1
    assert "computedHash" in lock_violations[0].message


def test_exact_filename_excludes_and_vendored_trees(tmp_path: Path) -> None:
    _write_lock(tmp_path / "skills-lock.json", {"version": 1, "skills": {}})
    _write_lock(tmp_path / ".skill-lock.json", {"version": 1, "skills": {}})
    _write_lock(
        tmp_path / "packages" / "private" / "skills-lock.json",
        {"version": 1, "skills": {}},
    )
    _write_lock(
        tmp_path / "vendor" / "dependency" / "skills-lock.json",
        {"version": 1, "skills": {}},
    )

    context = RepositoryContext(tmp_path, exclude_patterns=["packages/private/**"])

    assert context.skills_lock_files() == [tmp_path / "skills-lock.json"]
    assert [block.path for block in context.lint_tree.find(SkillsLockBlock)] == [
        tmp_path / "skills-lock.json"
    ]


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        ('{"version": 1, "skills": {}, "bad": NaN}', "Invalid JSON"),
        ('{"version": 1, "skills": {}, "skills": {}}', "duplicate JSON object key"),
        ("[]", "must contain a JSON object"),
        ('{"version": 1,', "Invalid JSON"),
    ],
)
def test_strict_json_and_top_level_shape(tmp_path: Path, contents: str, expected: str) -> None:
    (tmp_path / "skills-lock.json").write_text(contents)

    messages = _messages(tmp_path)

    assert len(messages) == 1
    assert expected in messages[0]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"skills": {}}, "Missing required top-level field 'version'"),
        ({"version": True, "skills": {}}, "'version' must be a number"),
        ({"version": 0, "skills": {}}, "'version' must be at least 1"),
        ({"version": 1}, "Missing required top-level field 'skills'"),
        ({"version": 1, "skills": []}, "'skills' must be an object"),
    ],
)
def test_required_top_level_fields(tmp_path: Path, data: dict, expected: str) -> None:
    _write_lock(tmp_path / "skills-lock.json", data)

    assert any(expected in message for message in _messages(tmp_path))


def test_invalid_fixture_reports_each_broken_field(tmp_path: Path) -> None:
    repo = _copy_fixture("skills-lock/invalid", tmp_path)

    violations = SkillsLockValidRule().check(RepositoryContext(repo))
    messages = [violation.message for violation in violations]

    assert any("newer than the supported version" in message for message in messages)
    assert any("Skill names" in message for message in messages)
    assert any("must be an object" in message for message in messages)
    assert any("field 'source'" in message for message in messages)
    assert any("unrecognized sourceType" in message for message in messages)
    assert any("computedHash" in message for message in messages)
    assert any("optional field 'sourceUrl'" in message for message in messages)
    assert any("optional field 'ref'" in message for message in messages)
    assert any("subagents[1]" in message for message in messages)
    assert any("stay relative" in message for message in messages)
    assert any("must end with 'SKILL.md'" in message for message in messages)
    assert any("wellKnownDigest" in message for message in messages)
    assert all(violation.line is None for violation in violations)


def test_git_restore_and_local_portability_warnings(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {
            "version": 1,
            "skills": {
                "gitlab-skill": _entry(source="group/project", sourceType="gitlab"),
                "local-posix": _entry(source="/opt/team/skill", sourceType="local"),
                "local-windows": _entry(source="C:\\team\\skill", sourceType="local"),
                "backslash-path": _entry(skillPath="skills\\demo\\SKILL.md"),
            },
        },
    )

    violations = SkillsLockValidRule().check(RepositoryContext(tmp_path))
    warnings = [v.message for v in violations if v.severity == Severity.WARNING]

    assert any("without 'sourceUrl'" in message for message in warnings)
    assert sum("absolute local source path" in message for message in warnings) == 2
    assert any("uses backslashes" in message for message in warnings)
    assert all(v.severity == Severity.WARNING for v in violations)


@pytest.mark.parametrize(
    "skill_path",
    [
        "C:skills/SKILL.md",
        "\\skills\\demo\\SKILL.md",
    ],
)
def test_skill_path_rejects_windows_root_and_drive_relative_forms(
    tmp_path: Path, skill_path: str
) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {"version": 1, "skills": {"unsafe": _entry(skillPath=skill_path)}},
    )

    assert any("stay relative" in message for message in _messages(tmp_path))


def test_skill_path_requires_skill_md_as_final_component(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {
            "version": 1,
            "skills": {"lookalike": _entry(skillPath="skills/demo/NOTSKILL.md")},
        },
    )

    assert any("must end with 'SKILL.md'" in message for message in _messages(tmp_path))


def test_skill_path_rejects_nul(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {"version": 1, "skills": {"unsafe": _entry(skillPath="skills/\0/SKILL.md")}},
    )

    assert any("must not contain NUL" in message for message in _messages(tmp_path))


def test_unknown_source_type_can_be_allowlisted(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {
            "version": 1,
            "skills": {"registry-skill": _entry(source="registry:id", sourceType="registry")},
        },
    )

    violations = SkillsLockValidRule().check(RepositoryContext(tmp_path))
    assert len(violations) == 1
    assert violations[0].severity == Severity.INFO
    assert "extra-source-types" in violations[0].message

    configured = {"extra-source-types": ["registry"]}
    assert SkillsLockValidRule(configured).check(RepositoryContext(tmp_path)) == []

    # Config validation normally rejects this shape before a rule runs. The
    # rule still stands down safely when instantiated directly by an API user.
    malformed = {"extra-source-types": "registry"}
    violations = SkillsLockValidRule(malformed).check(RepositoryContext(tmp_path))
    assert len(violations) == 1


def test_optional_fields_accept_empty_subagent_name_but_not_empty_strings(
    tmp_path: Path,
) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {
            "version": 1,
            "skills": {
                "valid": _entry(subagents=[""], skillPath="SKILL.md"),
                "invalid": _entry(sourceUrl=" ", wellKnownDigest=" ", subagents="reviewer"),
            },
        },
    )

    messages = _messages(tmp_path)

    assert len(messages) == 3
    assert any("sourceUrl" in message for message in messages)
    assert any("wellKnownDigest" in message for message in messages)
    assert any("subagents" in message for message in messages)


def test_external_lock_entries_tag_installed_skill_tree(tmp_path: Path) -> None:
    repo = _copy_fixture("skills-lock/external", tmp_path)
    context = RepositoryContext(repo)
    nodes = {node.path.name: node for node in context.lint_tree.find(SkillNode)}

    external = nodes["external-dep"]
    assert external.externally_sourced
    assert external.in_external_source
    assert all(block.in_external_source for block in external.children)

    assert not nodes["local-copy"].externally_sourced
    assert not nodes["local-source"].externally_sourced
    assert not nodes["authored-skill"].externally_sourced


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("My Skill", "my-skill"),
        ("../", "unnamed-skill"),
        ("A" * 300, "a" * 255),
    ],
)
def test_install_name_sanitization_matches_skills_cli(name: str, expected: str) -> None:
    assert skills_lock.sanitize_install_name(name) == expected


def test_local_source_externality_uses_repository_containment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    assert not skills_lock.entry_is_external(
        {"sourceType": "local", "source": "./skills/source"},
        lock_root=repo,
        repository_root=repo,
    )
    assert skills_lock.entry_is_external(
        {"sourceType": "local", "source": "../outside"},
        lock_root=repo,
        repository_root=repo,
    )
    assert skills_lock.entry_is_external(
        {"sourceType": "local", "source": "C:\\outside\\skill"},
        lock_root=repo,
        repository_root=repo,
    )
    assert skills_lock.entry_is_external(
        {"sourceType": "github", "source": "example/skills"},
        lock_root=repo,
        repository_root=repo,
    )
    assert skills_lock.entry_is_external(
        {"sourceType": "local"},
        lock_root=repo,
        repository_root=repo,
    )


def test_copy_target_is_external_even_when_lockfile_diagnostics_are_excluded(
    tmp_path: Path,
) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {"version": 1, "skills": {"Remote Skill": _entry()}},
    )
    # Copy-mode targets need not use a conventional dot-directory. Eve's
    # project path is one real Vercel target that skillsaw discovers.
    skill = tmp_path / "agent" / "skills" / "remote-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: remote-skill\ndescription: Use when testing a copied target.\n---\n"
    )
    context = RepositoryContext(
        tmp_path,
        exclude_patterns=["skills-lock.json"],
        lint_external_content=False,
    )

    assert context.skills_lock_files() == []
    assert context.is_externally_sourced_skill(skill)
    assert context.externally_sourced_skill_roots() == {skill.resolve()}
    assert context.lint_tree.find(SkillsLockBlock) == []
    assert context.lint_tree.find(SkillNode) == []


def test_external_matching_uses_nearest_nested_lock(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {"version": 1, "skills": {"shared": _entry()}},
    )
    nested = tmp_path / "packages" / "web"
    _write_lock(nested / "skills-lock.json", {"version": 1, "skills": {}})
    # Use a non-hidden Vercel target so recursive discovery reaches it; an
    # unknown hidden directory would be intentionally skipped and make this
    # precedence assertion vacuous.
    skill = nested / "agent" / "skills" / "shared"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Use when testing a nested project.\n---\n"
    )

    context = RepositoryContext(tmp_path)

    assert skill in context.skills
    assert not context.is_externally_sourced_skill(skill)


def test_malformed_nested_lock_remains_a_project_boundary(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {"version": 1, "skills": {"shared": _entry()}},
    )
    nested = tmp_path / "packages" / "web"
    nested.mkdir(parents=True)
    (nested / "skills-lock.json").write_text("{broken")
    skill = nested / "agent" / "skills" / "shared"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Use when testing a malformed nested lock.\n---\n"
    )

    context = RepositoryContext(tmp_path, lint_external_content=False)

    assert [node.path for node in context.lint_tree.find(SkillNode)] == [skill]
    assert not context.is_externally_sourced_skill(skill)


def test_escaping_lockfile_symlink_is_not_read_for_provenance(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside-lock.json"
    _write_lock(outside, {"version": 1, "skills": {"external-dep": _entry()}})
    (repo / "skills-lock.json").symlink_to(outside)
    skill = repo / ".agents" / "skills" / "external-dep"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: external-dep\ndescription: Use when testing a lock symlink.\n---\n"
    )

    context = RepositoryContext(repo, lint_external_content=False)

    assert [node.path for node in context.lint_tree.find(SkillNode)] == [skill]
    assert not context.is_externally_sourced_skill(skill)


def test_malformed_lock_fails_open_for_skill_linting(tmp_path: Path) -> None:
    (tmp_path / "skills-lock.json").write_text("{broken")
    skill = tmp_path / ".agents" / "skills" / "external-dep"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: external-dep\ndescription: Use when testing malformed provenance.\n---\n"
    )

    context = RepositoryContext(tmp_path, lint_external_content=False)

    assert [node.path for node in context.lint_tree.find(SkillNode)] == [skill]
    assert not context.is_externally_sourced_skill(skill)


@pytest.mark.parametrize(
    "entry",
    [
        {},
        {
            "source": "example/external-skills",
            "sourceType": "github",
            "computedHash": "not-a-sha256",
        },
    ],
)
def test_structurally_invalid_lock_entry_fails_open_for_skill_linting(
    tmp_path: Path, entry: dict[str, object]
) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {"version": 1, "skills": {"external-dep": entry}},
    )
    skill = tmp_path / ".agents" / "skills" / "external-dep"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: external-dep\ndescription: Use when testing invalid provenance.\n---\n"
    )

    context = RepositoryContext(tmp_path, lint_external_content=False)

    assert [node.path for node in context.lint_tree.find(SkillNode)] == [skill]
    assert not context.is_externally_sourced_skill(skill)


def test_cli_reports_external_findings_but_never_advertises_a_fix(tmp_path: Path) -> None:
    repo = _copy_fixture("skills-lock/external", tmp_path)

    result = run_cli(
        ["lint", repo, "--rule", "agentskill-name", "--format", "json", "--no-progress"]
    )
    report = json.loads(result.stdout)
    by_path = {Path(v["file_path"]): v for v in report["violations"]}

    external = Path(".agents/skills/external-dep/SKILL.md")
    local_copy = Path(".agents/skills/local-copy/SKILL.md")
    authored = Path("skills/authored-skill/SKILL.md")
    assert external in by_path
    assert by_path[external]["fixable"] is False
    assert by_path[local_copy]["fixable"] is True
    assert by_path[authored]["fixable"] is True


def test_cli_can_lint_only_repository_controlled_skills(tmp_path: Path) -> None:
    repo = _copy_fixture("skills-lock/external", tmp_path)
    config = repo / ".skillsaw.yaml"
    config.write_text('version: "0.20.0"\nlint-external-content: false\n')

    result = run_cli(
        [
            "lint",
            repo,
            "--config",
            config,
            "--rule",
            "agentskill-name",
            "--format",
            "json",
            "--no-progress",
        ]
    )
    paths = {Path(v["file_path"]) for v in json.loads(result.stdout)["violations"]}

    assert Path(".agents/skills/external-dep/SKILL.md") not in paths
    assert Path(".agents/skills/local-copy/SKILL.md") in paths
    assert Path("skills/authored-skill/SKILL.md") in paths


def test_fix_never_rewrites_an_external_lock_managed_skill(tmp_path: Path) -> None:
    repo = _copy_fixture("skills-lock/external", tmp_path)
    external = repo / ".agents" / "skills" / "external-dep" / "SKILL.md"
    local_copy = repo / ".agents" / "skills" / "local-copy" / "SKILL.md"
    authored = repo / "skills" / "authored-skill" / "SKILL.md"
    original = external.read_text()

    result = run_cli(["fix", repo, "--rule", "agentskill-name", "--no-progress"])

    assert result.returncode == 0
    assert external.read_text() == original
    assert "name: local-copy" in local_copy.read_text()
    assert "name: authored-skill" in authored.read_text()


def test_targeted_fix_never_rewrites_an_external_lock_managed_skill(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture("skills-lock/external", tmp_path)
    external_dir = repo / ".agents" / "skills" / "external-dep"
    external = external_dir / "SKILL.md"
    original = external.read_text()

    context = RepositoryContext(external_dir)
    lint_result = run_cli(
        ["lint", external_dir, "--rule", "agentskill-name", "--format", "json", "--no-progress"]
    )
    result = run_cli(["fix", external_dir, "--rule", "agentskill-name", "--no-progress"])
    violations = json.loads(lint_result.stdout)["violations"]

    assert context.is_externally_sourced(external_dir)
    assert len(violations) == 1
    assert violations[0]["fixable"] is False
    assert result.returncode == 0
    assert external.read_text() == original


def test_missing_computed_hash_is_a_warning(tmp_path: Path) -> None:
    """`npx skills list`/`add`/`update` process an entry without `computedHash`;
    only the drift check needs it. A hand-maintained lockfile is not broken."""
    repo = tmp_path / "repo"
    (repo / ".agents" / "skills" / "hashless").mkdir(parents=True)
    (repo / ".agents" / "skills" / "hashless" / "SKILL.md").write_text(
        "---\nname: hashless\ndescription: Installed by hand. Use when asked to demo.\n---\nDemo.\n"
    )
    _write_lock(
        repo / "skills-lock.json",
        {
            "version": 1,
            "skills": {"hashless": {"source": "example/skills", "sourceType": "github"}},
        },
    )

    found = SkillsLockValidRule().check(RepositoryContext(repo))

    assert [(v.severity, "computedHash" in v.message) for v in found] == [(Severity.WARNING, True)]


def test_self_installed_skill_is_the_repository_s_own_content(tmp_path: Path) -> None:
    """A repository that publishes a skill and installs it from its own GitHub
    coordinates records itself as the source. That entry describes authored
    content: the authored copy is not external, and autofix may touch it.
    An entry from any other repository is still external."""
    repo = tmp_path / "clonecn"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_text(
        '[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n'
        "\turl = git@github.com:hunvreus/CloneCN.git\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
    )
    for name in ("clonecn", "external-dep"):
        (repo / "skills" / name).mkdir(parents=True)
        (repo / "skills" / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Does {name} things. Use when asked.\n---\nBody.\n"
        )
    _write_lock(
        repo / "skills-lock.json",
        {
            "version": 1,
            "skills": {
                "clonecn": _entry(source="hunvreus/clonecn", skillPath="skills/clonecn/SKILL.md"),
                "external-dep": _entry(source="someone-else/skills"),
            },
        },
    )

    nodes = {node.path.name: node for node in RepositoryContext(repo).lint_tree.find(SkillNode)}

    assert not nodes["clonecn"].externally_sourced
    assert nodes["external-dep"].externally_sourced


def test_self_source_detection_needs_a_git_origin(tmp_path: Path) -> None:
    """Without a `.git/config` there is nothing to compare the source with, so
    the entry keeps its external verdict — the established behaviour."""
    repo = tmp_path / "tarball"
    (repo / "skills" / "clonecn").mkdir(parents=True)
    (repo / "skills" / "clonecn" / "SKILL.md").write_text(
        "---\nname: clonecn\ndescription: Clones things. Use when asked.\n---\nBody.\n"
    )
    _write_lock(
        repo / "skills-lock.json",
        {"version": 1, "skills": {"clonecn": _entry(source="hunvreus/clonecn")}},
    )

    nodes = {node.path.name: node for node in RepositoryContext(repo).lint_tree.find(SkillNode)}

    assert nodes["clonecn"].externally_sourced


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("hunvreus/clonecn", "hunvreus/clonecn"),
        ("github:Hunvreus/CloneCN", "hunvreus/clonecn"),
        ("https://github.com/hunvreus/clonecn.git", "hunvreus/clonecn"),
        ("git@github.com:hunvreus/clonecn.git", "hunvreus/clonecn"),
        ("https://github.com/hunvreus/clonecn/tree/main/skills#ref", "hunvreus/clonecn"),
        ("hunvreus/clonecn@v1", "hunvreus/clonecn"),
        ("github.com/hunvreus/clonecn", "hunvreus/clonecn"),
        ("https://gitlab.com/group/project", None),
        ("git@gitlab.com:group/project.git", None),
        ("./skills/local", None),
        ("clonecn", None),
        ("/", None),
    ],
)
def test_github_owner_repo_normalizes_every_source_spelling(source, expected) -> None:
    assert skills_lock.github_owner_repo(source) == expected


def test_own_repository_needs_an_origin_url(tmp_path: Path) -> None:
    """A `.git/config` without an origin remote, or an origin without a url,
    identifies nothing; an unreadable config is the same as none."""
    from skillsaw.repository_external_content import RepositoryExternalContentMixin

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert RepositoryExternalContentMixin._github_repository_of(repo) is None

    (repo / ".git" / "config").write_text("[core]\n\tbare = false\n")
    assert RepositoryExternalContentMixin._github_repository_of(repo) is None

    (repo / ".git" / "config").write_text('[remote "origin"]\n\tfetch = +refs/heads/*\n')
    assert RepositoryExternalContentMixin._github_repository_of(repo) is None

    (repo / ".git" / "config").write_text(
        '[remote "upstream"]\n\turl = git@github.com:other/repo.git\n'
        '[remote "origin"]\n\turl = https://github.com/Owner/Repo.git\n'
    )
    assert RepositoryExternalContentMixin._github_repository_of(repo) == "owner/repo"
