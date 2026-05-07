"""
Tests for agentskills.io rules and detection
"""

import json
from pathlib import Path

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.agentskills import (
    AgentSkillValidRule,
    AgentSkillNameRule,
    AgentSkillDescriptionRule,
    AgentSkillStructureRule,
    AgentSkillEvalsRequiredRule,
    AgentSkillEvalsRule,
)

# --- Detection tests ---


def test_detect_single_skill(temp_dir):
    """Single SKILL.md at root -> AGENTSKILLS"""
    skill_dir = temp_dir / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A skill\n---\n")

    context = RepositoryContext(skill_dir)
    assert context.repo_type == RepositoryType.AGENTSKILLS
    assert len(context.skills) == 1
    assert context.skills[0] == skill_dir.resolve()


def test_detect_skill_collection(temp_dir):
    """Subdirectories with SKILL.md -> AGENTSKILLS"""
    repo = temp_dir / "skills-repo"
    repo.mkdir()

    for name in ["skill-one", "skill-two"]:
        d = repo / name
        d.mkdir()
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: A skill\n---\n")

    context = RepositoryContext(repo)
    assert context.repo_type == RepositoryType.AGENTSKILLS
    assert len(context.skills) == 2


def test_detect_standard_discovery_path(temp_dir):
    """Skills in .claude/skills/ -> DOT_CLAUDE (not AGENTSKILLS)"""
    repo = temp_dir / "project"
    repo.mkdir()
    skills_path = repo / ".claude" / "skills" / "my-skill"
    skills_path.mkdir(parents=True)
    (skills_path / "SKILL.md").write_text("---\nname: my-skill\ndescription: A skill\n---\n")

    context = RepositoryContext(repo)
    assert context.repo_type == RepositoryType.DOT_CLAUDE
    assert len(context.skills) == 1


def test_detect_github_skills_path(temp_dir):
    """Skills in .github/skills/ -> AGENTSKILLS"""
    repo = temp_dir / "project"
    repo.mkdir()
    skills_path = repo / ".github" / "skills" / "review"
    skills_path.mkdir(parents=True)
    (skills_path / "SKILL.md").write_text("---\nname: review\ndescription: Code review\n---\n")

    context = RepositoryContext(repo)
    assert context.repo_type == RepositoryType.AGENTSKILLS
    assert len(context.skills) == 1


def test_detect_nested_skill_collection(temp_dir):
    """Skills nested in category subdirectories -> AGENTSKILLS"""
    repo = temp_dir / "skills-repo"
    repo.mkdir()

    nested = repo / "category" / "my-skill"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("---\nname: my-skill\ndescription: Nested skill\n---\n")

    context = RepositoryContext(repo)
    assert context.repo_type == RepositoryType.AGENTSKILLS
    assert len(context.skills) == 1
    assert context.skills[0].name == "my-skill"


def test_detect_not_agentskills(temp_dir):
    """Empty directory -> UNKNOWN"""
    repo = temp_dir / "empty"
    repo.mkdir()

    context = RepositoryContext(repo)
    assert context.repo_type == RepositoryType.UNKNOWN
    assert len(context.skills) == 0


def test_plugin_repo_discovers_embedded_skills(temp_dir):
    """Plugin repos also discover embedded skills"""
    plugin = temp_dir / "my-plugin"
    plugin.mkdir()
    claude_dir = plugin / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(json.dumps({"name": "my-plugin"}))

    skill_dir = plugin / "skills" / "helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: helper\ndescription: Helper\n---\n")

    context = RepositoryContext(plugin)
    assert context.repo_type == RepositoryType.SINGLE_PLUGIN
    assert len(context.skills) == 1
    assert context.skills[0].name == "helper"


def test_plugin_takes_priority_over_agentskills(temp_dir):
    """Plugin detection wins over agentskills when .claude-plugin exists"""
    repo = temp_dir / "hybrid"
    repo.mkdir()
    claude_dir = repo / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(json.dumps({"name": "hybrid"}))
    (repo / "SKILL.md").write_text("---\nname: hybrid\ndescription: Both\n---\n")

    context = RepositoryContext(repo)
    assert context.repo_type == RepositoryType.SINGLE_PLUGIN


# --- agentskill-valid ---


def test_valid_skill_passes(temp_dir):
    skill = temp_dir / "good-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: good-skill\ndescription: Does good things.\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert len(violations) == 0


def test_missing_skill_md_fails(temp_dir):
    repo = temp_dir / "repo"
    repo.mkdir()
    skill = repo / "no-skill-md"
    skill.mkdir()
    # Create another valid skill so the repo is detected as AGENTSKILLS
    other = repo / "valid-skill"
    other.mkdir()
    (other / "SKILL.md").write_text("---\nname: valid-skill\ndescription: Valid\n---\n")
    # Manually add the broken skill to context
    context = RepositoryContext(repo)
    context.skills.append(skill)

    violations = AgentSkillValidRule().check(context)
    missing = [v for v in violations if "not found" in v.message]
    assert len(missing) == 1


def test_missing_frontmatter_fails(temp_dir):
    skill = temp_dir / "no-front"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# Just markdown\nNo frontmatter here.\n")

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert len(violations) == 1
    assert "frontmatter" in violations[0].message.lower()


def test_missing_name_fails(temp_dir):
    skill = temp_dir / "no-name"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\ndescription: Has description only\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert any("name" in v.message for v in violations)


def test_missing_description_fails(temp_dir):
    skill = temp_dir / "no-desc"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: no-desc\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert any("description" in v.message for v in violations)


def test_name_too_long_fails(temp_dir):
    skill = temp_dir / "long"
    skill.mkdir()
    long_name = "a" * 65
    (skill / "SKILL.md").write_text(f"---\nname: {long_name}\ndescription: Too long name\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert any("exceeds" in v.message and "64" in v.message for v in violations)


def test_description_too_long_checked_by_description_rule(temp_dir):
    """Length check is in AgentSkillDescriptionRule, not AgentSkillValidRule"""
    skill = temp_dir / "longdesc"
    skill.mkdir()
    long_desc = "a" * 1025
    (skill / "SKILL.md").write_text(f"---\nname: longdesc\ndescription: {long_desc}\n---\n")

    context = RepositoryContext(skill)
    # AgentSkillValidRule should NOT flag length
    violations = AgentSkillValidRule().check(context)
    assert not any("exceeds" in v.message for v in violations)
    # AgentSkillDescriptionRule should flag it
    violations = AgentSkillDescriptionRule().check(context)
    assert any("exceeds" in v.message and "1024" in v.message for v in violations)


# --- agentskill-name ---


def test_name_valid_passes(temp_dir):
    skill = temp_dir / "pdf-processing"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: pdf-processing\ndescription: PDFs\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillNameRule().check(context)
    assert len(violations) == 0


def test_name_with_numbers_passes(temp_dir):
    skill = temp_dir / "tool2use"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: tool2use\ndescription: Tools\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillNameRule().check(context)
    assert len(violations) == 0


def test_name_single_char_passes(temp_dir):
    skill = temp_dir / "x"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: x\ndescription: Single char\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillNameRule().check(context)
    assert len(violations) == 0


def test_name_uppercase_fails(temp_dir):
    skill = temp_dir / "Bad-Name"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: Bad-Name\ndescription: Uppercase\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillNameRule().check(context)
    assert len(violations) >= 1
    assert any("lowercase" in v.message for v in violations)


def test_name_consecutive_hyphens_fails(temp_dir):
    skill = temp_dir / "bad--name"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: bad--name\ndescription: Double hyphen\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillNameRule().check(context)
    assert any("consecutive" in v.message for v in violations)


def test_name_trailing_hyphen_fails(temp_dir):
    skill = temp_dir / "bad-"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: bad-\ndescription: Trailing hyphen\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillNameRule().check(context)
    assert len(violations) >= 1


def test_name_dir_mismatch_fails(temp_dir):
    repo = temp_dir / "repo"
    repo.mkdir()
    skill = repo / "dir-name"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: other-name\ndescription: Mismatch\n---\n")

    context = RepositoryContext(repo)
    violations = AgentSkillNameRule().check(context)
    assert any("does not match directory" in v.message for v in violations)


def test_name_at_root_skips_dir_check(temp_dir):
    """Single skill at repo root should not check name vs directory name"""
    skill = temp_dir / "my-project"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: my-skill\ndescription: Root skill\n---\n")

    context = RepositoryContext(skill)
    # root_path is skill dir, so name vs dir check is skipped
    violations = AgentSkillNameRule().check(context)
    assert not any("does not match directory" in v.message for v in violations)


# --- agentskill-description ---


def test_description_valid_passes(temp_dir):
    skill = temp_dir / "good"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: good\ndescription: Extracts data from PDFs. Use when working with PDF files.\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillDescriptionRule().check(context)
    assert len(violations) == 0


def test_description_whitespace_only_fails(temp_dir):
    skill = temp_dir / "empty-desc"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: empty-desc\ndescription: '   '\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillDescriptionRule().check(context)
    assert any("empty" in v.message for v in violations)


def test_description_over_limit_warns(temp_dir):
    skill = temp_dir / "verbose"
    skill.mkdir()
    long_desc = "x" * 1025
    (skill / "SKILL.md").write_text(f"---\nname: verbose\ndescription: {long_desc}\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillDescriptionRule().check(context)
    assert any("exceeds" in v.message for v in violations)


# --- agentskill-structure ---


def test_structure_known_dirs_pass(temp_dir):
    skill = temp_dir / "structured"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: structured\ndescription: Well structured\n---\n")
    for d in ["scripts", "references", "assets", "evals"]:
        (skill / d).mkdir()

    context = RepositoryContext(skill)
    violations = AgentSkillStructureRule().check(context)
    assert len(violations) == 0


def test_structure_unknown_dir_warns(temp_dir):
    skill = temp_dir / "messy"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: messy\ndescription: Messy skill\n---\n")
    (skill / "random-stuff").mkdir()

    context = RepositoryContext(skill)
    violations = AgentSkillStructureRule().check(context)
    assert len(violations) == 1
    assert "random-stuff" in violations[0].message


def test_structure_ignores_dotdirs(temp_dir):
    skill = temp_dir / "hidden"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: hidden\ndescription: Has hidden dir\n---\n")
    (skill / ".git").mkdir()

    context = RepositoryContext(skill)
    violations = AgentSkillStructureRule().check(context)
    assert len(violations) == 0


def test_structure_ignores_files(temp_dir):
    skill = temp_dir / "with-files"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: with-files\ndescription: Has extra files\n---\n")
    (skill / "README.md").write_text("# Hello")
    (skill / "LICENSE").write_text("MIT")

    context = RepositoryContext(skill)
    violations = AgentSkillStructureRule().check(context)
    assert len(violations) == 0


# --- agentskill-evals-required ---


def test_evals_required_disabled_by_default(temp_dir):
    """Rule should be disabled by default (tested via config, not rule directly)"""
    from skillsaw.config import LinterConfig

    config = LinterConfig.default()
    assert config.get_rule_config("agentskill-evals-required").get("enabled") is False


def test_evals_required_fails_when_missing(temp_dir):
    skill = temp_dir / "no-evals"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: no-evals\ndescription: No evals\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRequiredRule().check(context)
    assert len(violations) == 1
    assert "Missing evals/evals.json" in violations[0].message


def test_evals_required_passes_when_present(temp_dir):
    skill = temp_dir / "has-evals"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: has-evals\ndescription: Has evals\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(json.dumps({"evals": []}))

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRequiredRule().check(context)
    assert len(violations) == 0


# --- agentskill-evals ---


def test_evals_valid_passes(temp_dir):
    skill = temp_dir / "good-evals"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: good-evals\ndescription: Good evals\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps(
            {
                "skill_name": "good-evals",
                "evals": [
                    {
                        "id": 1,
                        "prompt": "Test this thing",
                        "expected_output": "Should produce output",
                        "assertions": ["Output is valid", "Output contains X"],
                        "files": ["evals/files/input.csv"],
                    }
                ],
            }
        )
    )

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert len(violations) == 0


def test_evals_no_evals_dir_skips(temp_dir):
    skill = temp_dir / "no-evals-dir"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: no-evals-dir\ndescription: No evals dir\n---\n")

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert len(violations) == 0


def test_evals_dir_without_json_warns(temp_dir):
    skill = temp_dir / "empty-evals"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: empty-evals\ndescription: Empty evals\n---\n")
    (skill / "evals").mkdir()

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert len(violations) == 1
    assert "missing" in violations[0].message.lower()


def test_evals_invalid_json_fails(temp_dir):
    skill = temp_dir / "bad-json"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: bad-json\ndescription: Bad json\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text("{not valid json")

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert len(violations) == 1
    assert "Invalid JSON" in violations[0].message


def test_evals_missing_evals_array_fails(temp_dir):
    skill = temp_dir / "no-array"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: no-array\ndescription: No array\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(json.dumps({"skill_name": "test"}))

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert any("evals" in v.message and "array" in v.message.lower() for v in violations)


def test_evals_entry_missing_id_warns(temp_dir):
    skill = temp_dir / "no-id"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: no-id\ndescription: No id\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(json.dumps({"evals": [{"prompt": "Test"}]}))

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert any("id" in v.message for v in violations)


def test_evals_entry_missing_prompt_warns(temp_dir):
    skill = temp_dir / "no-prompt"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: no-prompt\ndescription: No prompt\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(json.dumps({"evals": [{"id": 1}]}))

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert any("prompt" in v.message for v in violations)


def test_evals_bad_assertions_type_warns(temp_dir):
    skill = temp_dir / "bad-assertions"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: bad-assertions\ndescription: Bad assertions\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps({"evals": [{"id": 1, "prompt": "Test", "assertions": "not an array"}]})
    )

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert any("assertions" in v.message and "array" in v.message for v in violations)


def test_evals_assertions_not_strings_warns(temp_dir):
    skill = temp_dir / "int-assertions"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: int-assertions\ndescription: Int assertions\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps({"evals": [{"id": 1, "prompt": "Test", "assertions": [1, 2, 3]}]})
    )

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert any("strings" in v.message for v in violations)


def test_evals_duplicate_ids_warns(temp_dir):
    skill = temp_dir / "dup-ids"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: dup-ids\ndescription: Duplicate ids\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps(
            {
                "evals": [
                    {"id": 1, "prompt": "A"},
                    {"id": 1, "prompt": "B"},
                    {"id": 2, "prompt": "C"},
                ]
            }
        )
    )

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert any("duplicate" in v.message.lower() for v in violations)


def test_evals_skill_name_mismatch_warns(temp_dir):
    skill = temp_dir / "name-check"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: name-check\ndescription: Name check\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps({"skill_name": "wrong-name", "evals": [{"id": 1, "prompt": "Test"}]})
    )

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert any("does not match" in v.message for v in violations)


def test_evals_skill_name_match_passes(temp_dir):
    skill = temp_dir / "matching"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: matching\ndescription: Matching name\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps({"skill_name": "matching", "evals": [{"id": 1, "prompt": "Test"}]})
    )

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert len(violations) == 0


def test_evals_bad_files_type_warns(temp_dir):
    skill = temp_dir / "bad-files"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: bad-files\ndescription: Bad files\n---\n")
    evals_dir = skill / "evals"
    evals_dir.mkdir()
    (evals_dir / "evals.json").write_text(
        json.dumps({"evals": [{"id": 1, "prompt": "Test", "files": "not-array"}]})
    )

    context = RepositoryContext(skill)
    violations = AgentSkillEvalsRule().check(context)
    assert any("files" in v.message and "array" in v.message for v in violations)


# --- optional frontmatter fields ---


def test_valid_optional_fields_pass(temp_dir):
    skill = temp_dir / "full-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: full-skill\ndescription: A skill\nlicense: MIT\n"
        'compatibility: Requires Python 3.8+\nallowed-tools: "Bash(git:*) Read"\n'
        "metadata:\n  version: '1.0'\n  author: test\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert len(violations) == 0


def test_license_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-license"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-license\ndescription: A skill\nlicense: 123\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert any("license" in v.message and "string" in v.message for v in violations)


def test_compatibility_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-compat"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-compat\ndescription: A skill\ncompatibility: 123\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert any("compatibility" in v.message and "string" in v.message for v in violations)


def test_compatibility_empty_fails(temp_dir):
    skill = temp_dir / "empty-compat"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: empty-compat\ndescription: A skill\ncompatibility: '  '\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert any("compatibility" in v.message and "empty" in v.message for v in violations)


def test_compatibility_over_limit_fails(temp_dir):
    skill = temp_dir / "long-compat"
    skill.mkdir()
    long_compat = "x" * 501
    (skill / "SKILL.md").write_text(
        f"---\nname: long-compat\ndescription: A skill\ncompatibility: {long_compat}\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert any("compatibility" in v.message and "exceeds" in v.message for v in violations)


def test_metadata_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-meta"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-meta\ndescription: A skill\nmetadata: not-a-map\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert any("metadata" in v.message and "mapping" in v.message for v in violations)


def test_metadata_non_string_value_accepted(temp_dir):
    skill = temp_dir / "meta-int"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: meta-int\ndescription: A skill\nmetadata:\n  count: 42\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert not any("metadata" in v.message for v in violations)


def test_metadata_nested_object_accepted(temp_dir):
    skill = temp_dir / "meta-nested"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: meta-nested\ndescription: A skill\nmetadata:\n"
        "  openclaw:\n    category: productivity\n    requires:\n      bins:\n        - gws\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert not any("metadata" in v.message for v in violations)


def test_allowed_tools_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-tools"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-tools\ndescription: A skill\nallowed-tools:\n  - Bash\n  - Read\n---\n"
    )

    context = RepositoryContext(skill)
    violations = AgentSkillValidRule().check(context)
    assert any("allowed-tools" in v.message and "string" in v.message for v in violations)
