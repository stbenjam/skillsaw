"""
Tests for APM (Agent Package Manager) detection, discovery, and rules
"""

from pathlib import Path

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.apm import (
    ApmYamlValidRule,
    ApmStructureValidRule,
)

# --- Helper to create an APM repo structure ---


def _make_apm_repo(root: Path, skills=None, instructions=False, apm_yml=None):
    """Create a minimal APM repo structure under root.

    Args:
        root: repo root directory (must already exist)
        skills: list of skill names to create under .apm/skills/
        instructions: whether to create .apm/instructions/
        apm_yml: content for apm.yml (None = default valid content)
    """
    apm_dir = root / ".apm"
    apm_dir.mkdir(exist_ok=True)

    if skills is not None:
        skills_dir = apm_dir / "skills"
        skills_dir.mkdir(exist_ok=True)
        for name in skills:
            skill_dir = skills_dir / name
            skill_dir.mkdir(exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: A test skill\n---\n"
            )

    if instructions:
        instr_dir = apm_dir / "instructions"
        instr_dir.mkdir(exist_ok=True)
        (instr_dir / "dev.instructions.md").write_text("# Dev instructions\n")

    if apm_yml is None:
        apm_yml = "name: test-repo\nversion: 1.0.0\ndescription: A test repo\n"
    if apm_yml is not False:
        (root / "apm.yml").write_text(apm_yml)


# --- APM detection tests ---


def test_detect_apm_repo(temp_dir):
    """Repo with .apm/skills/ should be detected as AGENTSKILLS"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["my-skill"])

    context = RepositoryContext(repo)
    assert context.has_apm is True
    assert context.repo_type == RepositoryType.AGENTSKILLS


def test_detect_apm_repo_instructions_only(temp_dir):
    """Repo with .apm/instructions/ but no skills should still detect APM"""
    repo = temp_dir / "instr-repo"
    repo.mkdir()
    _make_apm_repo(repo, instructions=True)

    context = RepositoryContext(repo)
    assert context.has_apm is True
    # No SKILL.md found, so repo type is UNKNOWN (not enough to be AGENTSKILLS)
    assert context.repo_type == RepositoryType.UNKNOWN


def test_apm_repo_discovers_skills(temp_dir):
    """Skills in .apm/skills/ are discovered"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["skill-a", "skill-b"])

    context = RepositoryContext(repo)
    assert len(context.skills) == 2
    skill_names = {s.name for s in context.skills}
    assert skill_names == {"skill-a", "skill-b"}


def test_apm_compiled_dirs_excluded(temp_dir):
    """Compiled output directories should not produce duplicate skill discoveries"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["my-skill"])

    # Create compiled output in .claude/skills/ (mimicking APM compile)
    compiled_skill = repo / ".claude" / "skills" / "my-skill"
    compiled_skill.mkdir(parents=True)
    (compiled_skill / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Compiled copy\n---\n"
    )

    context = RepositoryContext(repo)
    # Should only discover the .apm/ source, not the .claude/ compiled copy
    assert len(context.skills) == 1
    assert ".apm" in str(context.skills[0])


def test_apm_prevents_dot_claude_detection(temp_dir):
    """When .apm/ is present, .claude/ should not trigger DOT_CLAUDE detection"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["my-skill"])

    # Create .claude/ with skills (would normally be DOT_CLAUDE)
    claude_skills = repo / ".claude" / "skills" / "my-skill"
    claude_skills.mkdir(parents=True)
    (claude_skills / "SKILL.md").write_text("---\nname: my-skill\ndescription: Compiled\n---\n")

    context = RepositoryContext(repo)
    assert context.repo_type == RepositoryType.AGENTSKILLS
    assert context.repo_type != RepositoryType.DOT_CLAUDE


def test_apm_repo_with_top_level_skill_md(temp_dir):
    """APM repo with both .apm/skills/ and a top-level SKILL.md"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["my-skill"])

    # Also place a top-level SKILL.md (single-skill style)
    (repo / "SKILL.md").write_text(
        "---\nname: top-level-skill\ndescription: A top-level skill\n---\n"
    )

    context = RepositoryContext(repo)
    assert context.has_apm is True
    # Should still be detected as AGENTSKILLS (APM path wins)
    assert context.repo_type == RepositoryType.AGENTSKILLS
    # Should discover both the .apm/ skill and the top-level SKILL.md
    skill_names = {s.name for s in context.skills}
    assert "my-skill" in skill_names
    # The top-level SKILL.md uses the repo dir name as the skill "name"
    assert repo.name in skill_names or (repo / "SKILL.md").parent in [s for s in context.skills]


def test_no_apm_falls_through(temp_dir):
    """Without .apm/, detection should work as before"""
    repo = temp_dir / "normal-repo"
    repo.mkdir()

    context = RepositoryContext(repo)
    assert context.has_apm is False
    assert context.repo_type == RepositoryType.UNKNOWN


def test_apm_content_rules_apply(temp_dir):
    """Content rules (agentskill-valid etc.) should apply to .apm/ skills"""
    from skillsaw.rules.builtin.agentskills import AgentSkillValidRule

    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["good-skill"])

    context = RepositoryContext(repo)
    violations = AgentSkillValidRule().check(context)
    assert len(violations) == 0


def test_apm_content_rules_catch_errors(temp_dir):
    """Content rules should catch errors in .apm/ skills"""
    from skillsaw.rules.builtin.agentskills import AgentSkillValidRule

    repo = temp_dir / "apm-repo"
    repo.mkdir()
    (repo / ".apm" / "skills" / "bad-skill").mkdir(parents=True)
    (repo / ".apm" / "skills" / "bad-skill" / "SKILL.md").write_text(
        "---\ndescription: Missing name\n---\n"
    )
    (repo / "apm.yml").write_text("name: test\nversion: 1.0.0\ndescription: Test\n")

    context = RepositoryContext(repo)
    violations = AgentSkillValidRule().check(context)
    assert any("name" in v.message for v in violations)


# --- apm-yaml-valid ---


def test_apm_yaml_valid_passes(temp_dir):
    """Valid apm.yml should pass"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["my-skill"])

    context = RepositoryContext(repo)
    violations = ApmYamlValidRule().check(context)
    assert len(violations) == 0


def test_apm_yaml_missing_fails(temp_dir):
    """Missing apm.yml should fail"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["my-skill"], apm_yml=False)

    context = RepositoryContext(repo)
    violations = ApmYamlValidRule().check(context)
    assert len(violations) == 1
    assert "Missing apm.yml" in violations[0].message


def test_apm_yaml_invalid_yaml_fails(temp_dir):
    """Invalid YAML in apm.yml should fail"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["my-skill"], apm_yml="name: [invalid yaml\n")

    context = RepositoryContext(repo)
    violations = ApmYamlValidRule().check(context)
    assert len(violations) == 1
    assert "Invalid YAML" in violations[0].message


def test_apm_yaml_missing_name_fails(temp_dir):
    """Missing name field in apm.yml should fail"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(
        repo,
        skills=["my-skill"],
        apm_yml="version: 1.0.0\ndescription: No name\n",
    )

    context = RepositoryContext(repo)
    violations = ApmYamlValidRule().check(context)
    assert any("name" in v.message for v in violations)


def test_apm_yaml_missing_version_fails(temp_dir):
    """Missing version field in apm.yml should fail"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(
        repo,
        skills=["my-skill"],
        apm_yml="name: test\ndescription: No version\n",
    )

    context = RepositoryContext(repo)
    violations = ApmYamlValidRule().check(context)
    assert any("version" in v.message for v in violations)


def test_apm_yaml_missing_description_fails(temp_dir):
    """Missing description field in apm.yml should fail"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(
        repo,
        skills=["my-skill"],
        apm_yml="name: test\nversion: 1.0.0\n",
    )

    context = RepositoryContext(repo)
    violations = ApmYamlValidRule().check(context)
    assert any("description" in v.message for v in violations)


def test_apm_yaml_non_string_version_fails(temp_dir):
    """Non-string version field in apm.yml should fail"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(
        repo,
        skills=["my-skill"],
        apm_yml="name: test\nversion: 1.0\ndescription: Numeric version\n",
    )

    context = RepositoryContext(repo)
    violations = ApmYamlValidRule().check(context)
    # YAML parses 1.0 as a float, not a string — rule should catch this
    assert any("version" in v.message and "string" in v.message for v in violations)


def test_apm_yaml_not_mapping_fails(temp_dir):
    """apm.yml that is not a mapping should fail"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["my-skill"], apm_yml="- just\n- a\n- list\n")

    context = RepositoryContext(repo)
    violations = ApmYamlValidRule().check(context)
    assert any("mapping" in v.message for v in violations)


def test_apm_yaml_skipped_without_apm(temp_dir):
    """Rule should produce no violations when .apm/ is absent"""
    repo = temp_dir / "normal-repo"
    repo.mkdir()

    context = RepositoryContext(repo)
    violations = ApmYamlValidRule().check(context)
    assert len(violations) == 0


def test_apm_yaml_default_severity_is_error():
    """Default severity should be ERROR"""
    rule = ApmYamlValidRule()
    assert rule.default_severity() == Severity.ERROR


# --- apm-structure-valid ---


def test_apm_structure_valid_passes(temp_dir):
    """Valid .apm/ structure should pass"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, skills=["my-skill"])

    context = RepositoryContext(repo)
    violations = ApmStructureValidRule().check(context)
    assert len(violations) == 0


def test_apm_structure_instructions_only_passes(temp_dir):
    """Instructions-only .apm/ should pass"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, instructions=True)

    context = RepositoryContext(repo)
    violations = ApmStructureValidRule().check(context)
    assert len(violations) == 0


def test_apm_structure_empty_apm_dir_warns(temp_dir):
    """Empty .apm/ directory should warn"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    (repo / ".apm").mkdir()
    (repo / "apm.yml").write_text("name: test\nversion: 1.0.0\ndescription: Test\n")

    context = RepositoryContext(repo)
    violations = ApmStructureValidRule().check(context)
    assert len(violations) == 1
    assert "skills/" in violations[0].message or "instructions/" in violations[0].message


def test_apm_structure_skill_missing_skill_md_warns(temp_dir):
    """Skill directory without SKILL.md should warn"""
    repo = temp_dir / "apm-repo"
    repo.mkdir()
    (repo / ".apm" / "skills" / "broken-skill").mkdir(parents=True)
    (repo / "apm.yml").write_text("name: test\nversion: 1.0.0\ndescription: Test\n")

    context = RepositoryContext(repo)
    violations = ApmStructureValidRule().check(context)
    assert any("missing SKILL.md" in v.message for v in violations)


def test_apm_structure_skipped_without_apm(temp_dir):
    """Rule should produce no violations when .apm/ is absent"""
    repo = temp_dir / "normal-repo"
    repo.mkdir()

    context = RepositoryContext(repo)
    violations = ApmStructureValidRule().check(context)
    assert len(violations) == 0


def test_apm_structure_default_severity_is_warning():
    """Default severity should be WARNING"""
    rule = ApmStructureValidRule()
    assert rule.default_severity() == Severity.WARNING


# --- Config tests ---


def test_apm_rules_in_default_config():
    """APM rules should be in default config with auto-enable"""
    from skillsaw.config import LinterConfig

    config = LinterConfig.default()
    assert config.get_rule_config("apm-yaml-valid").get("enabled") == "auto"
    assert config.get_rule_config("apm-structure-valid").get("enabled") == "auto"


# --- Integration: linting this repo ---


def test_lint_real_apm_repo():
    """Smoke test: lint the skillsaw repo itself which has .apm/"""
    import os

    # Find the repo root (this test file is in tests/)
    repo_root = Path(__file__).resolve().parent.parent
    apm_dir = repo_root / ".apm"

    if not apm_dir.is_dir():
        # Skip if running from a location without .apm/
        return

    context = RepositoryContext(repo_root)
    assert context.has_apm is True
    # Skills should be discovered from .apm/skills/
    assert len(context.skills) > 0
    apm_skills = [s for s in context.skills if ".apm" in str(s)]
    assert len(apm_skills) > 0


# --- Content rules apply to APM files ---


def test_content_weak_language_in_apm_instructions(temp_dir):
    """content-weak-language should detect issues in .apm/instructions/ files."""
    from skillsaw.rules.builtin.content_rules import ContentWeakLanguageRule

    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, instructions=True)

    # Overwrite the instruction file with weak language
    instr_file = repo / ".apm" / "instructions" / "dev.instructions.md"
    instr_file.write_text("Try to handle errors gracefully if possible.\n")

    context = RepositoryContext(repo)
    rule = ContentWeakLanguageRule()
    violations = rule.check(context)
    assert len(violations) >= 1
    assert any(
        "try to" in v.message.lower() or "gracefully" in v.message.lower() for v in violations
    )


def test_content_weak_language_in_apm_agents(temp_dir):
    """content-weak-language should detect issues in .apm/agents/ files."""
    from skillsaw.rules.builtin.content_rules import ContentWeakLanguageRule

    repo = temp_dir / "apm-repo"
    repo.mkdir()
    apm_dir = repo / ".apm"
    agents_dir = apm_dir / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "reviewer.agent.md").write_text(
        "You should probably be careful when reviewing code.\n"
    )
    (repo / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")

    context = RepositoryContext(repo)
    rule = ContentWeakLanguageRule()
    violations = rule.check(context)
    assert len(violations) >= 1


def test_content_tautological_in_apm_instructions(temp_dir):
    """content-tautological should detect issues in .apm/instructions/ files."""
    from skillsaw.rules.builtin.content_rules import ContentTautologicalRule

    repo = temp_dir / "apm-repo"
    repo.mkdir()
    _make_apm_repo(repo, instructions=True)

    instr_file = repo / ".apm" / "instructions" / "dev.instructions.md"
    instr_file.write_text("Always write clean code and follow best practices.\n")

    context = RepositoryContext(repo)
    rule = ContentTautologicalRule()
    violations = rule.check(context)
    assert len(violations) >= 1
