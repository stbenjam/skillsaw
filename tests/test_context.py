"""
Tests for repository context detection
"""

import json
import sys
from pathlib import Path


from skillsaw.context import (
    RepositoryContext,
    RepositoryType,
    HAS_CURSOR,
    HAS_COPILOT,
    HAS_GEMINI,
    HAS_AGENTS_MD,
    HAS_KIRO,
    HAS_CLAUDE_MD,
    HAS_CODERABBIT,
)


def test_single_plugin_detection(valid_plugin):
    """Test detection of single plugin repository"""
    context = RepositoryContext(valid_plugin)
    assert context.repo_type == RepositoryType.SINGLE_PLUGIN
    assert len(context.plugins) == 1
    assert context.plugins[0].resolve() == valid_plugin.resolve()


def test_marketplace_detection(marketplace_repo):
    """Test detection of marketplace repository"""
    context = RepositoryContext(marketplace_repo)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 2
    assert context.has_marketplace()


def test_plugin_name_extraction(valid_plugin):
    """Test plugin name extraction"""
    context = RepositoryContext(valid_plugin)
    name = context.get_plugin_name(valid_plugin)
    assert name == "test-plugin"


def test_marketplace_registration(marketplace_repo):
    """Test marketplace registration check"""
    context = RepositoryContext(marketplace_repo)
    assert context.is_registered_in_marketplace("plugin-one")
    assert context.is_registered_in_marketplace("plugin-two")
    assert not context.is_registered_in_marketplace("plugin-three")


def test_unknown_repository(temp_dir):
    """Test detection of unknown repository type"""
    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.UNKNOWN
    assert len(context.plugins) == 0


def test_flat_structure_discovery(flat_structure_marketplace):
    """Test discovery of flat structure plugins (source: './')"""
    context = RepositoryContext(flat_structure_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 1
    assert context.plugins[0].resolve() == flat_structure_marketplace.resolve()


def test_flat_structure_name(flat_structure_marketplace):
    """Test plugin name extraction for flat structure"""
    context = RepositoryContext(flat_structure_marketplace)
    name = context.get_plugin_name(flat_structure_marketplace)
    assert name == "flat-plugin"


def test_custom_path_discovery(custom_path_marketplace):
    """Test discovery of plugins in custom directories"""
    context = RepositoryContext(custom_path_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 1
    expected_path = (custom_path_marketplace / "custom" / "my-plugin").resolve()
    assert context.plugins[0].resolve() == expected_path


def test_strict_false_without_plugin_json(strict_false_marketplace):
    """Test plugin discovery when strict: false and no plugin.json"""
    context = RepositoryContext(strict_false_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 1

    plugin_path = strict_false_marketplace / "my-plugin"
    assert plugin_path.resolve() in [p.resolve() for p in context.plugins]

    # Check metadata is stored (use resolved path)
    resolved_path = plugin_path.resolve()
    assert resolved_path in context.plugin_metadata
    assert context.plugin_metadata[resolved_path]["name"] == "no-manifest-plugin"


def test_strict_false_metadata_retrieval(strict_false_marketplace):
    """Test metadata retrieval for strict: false plugins"""
    context = RepositoryContext(strict_false_marketplace)
    plugin_path = strict_false_marketplace / "my-plugin"

    metadata = context.get_plugin_metadata(plugin_path)
    assert metadata is not None
    assert metadata["name"] == "no-manifest-plugin"
    assert metadata["version"] == "2.0.0"
    assert metadata["author"]["name"] == "Marketplace Author"


def test_plugin_json_precedence_over_marketplace(custom_path_marketplace):
    """
    plugin.json fields should take precedence over marketplace metadata when both exist.
    """
    context = RepositoryContext(custom_path_marketplace)
    plugin_dir = custom_path_marketplace / "custom" / "my-plugin"

    # Overwrite plugin.json with a conflicting name
    pj = plugin_dir / ".claude-plugin" / "plugin.json"
    obj = json.loads(pj.read_text())
    obj["name"] = "custom-plugin-from-json"
    pj.write_text(json.dumps(obj))

    # Recreate context to pick up changes
    context = RepositoryContext(custom_path_marketplace)

    # Name should come from plugin.json, not marketplace
    assert context.get_plugin_name(plugin_dir) == "custom-plugin-from-json"


def test_mixed_marketplace_discovery(mixed_marketplace):
    """Test discovery of plugins from both plugins/ dir and marketplace sources"""
    context = RepositoryContext(mixed_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 2

    plugin_names = [context.get_plugin_name(p) for p in context.plugins]
    assert "marketplace-plugin" in plugin_names
    assert "plugins-dir-plugin" in plugin_names


def test_remote_source_handling(remote_source_marketplace, caplog):
    """Test handling of remote plugin sources (GitHub, git URLs)"""
    import logging

    caplog.set_level(logging.INFO)

    context = RepositoryContext(remote_source_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    # Remote plugins should not be discovered locally
    assert len(context.plugins) == 0

    # Check that INFO messages were logged
    log_output = " ".join(record.message for record in caplog.records)
    assert "github-plugin" in log_output
    assert "git-plugin" in log_output
    assert "Skipping local validation" in log_output


def test_plugin_name_from_marketplace(strict_false_marketplace):
    """Test get_plugin_name uses marketplace data when plugin.json missing"""
    context = RepositoryContext(strict_false_marketplace)
    plugin_path = strict_false_marketplace / "my-plugin"

    name = context.get_plugin_name(plugin_path)
    assert name == "no-manifest-plugin"


def test_marketplace_registration_with_flat_structure(flat_structure_marketplace):
    """Test that flat structure plugins are registered in marketplace"""
    context = RepositoryContext(flat_structure_marketplace)
    assert context.is_registered_in_marketplace("flat-plugin")


def test_backward_compatibility_with_plugins_dir(marketplace_repo):
    """Test that existing plugins/ directory scanning still works"""
    context = RepositoryContext(marketplace_repo)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 2
    names = [context.get_plugin_name(p) for p in context.plugins]
    assert "plugin-one" in names
    assert "plugin-two" in names


def test_disallow_parent_traversal(temp_dir, caplog):
    """Do not allow marketplace sources to escape repo root with .."""
    import logging

    caplog.set_level(logging.WARNING)

    claude = temp_dir / ".claude-plugin"
    claude.mkdir()
    with open(claude / "marketplace.json", "w") as f:
        json.dump(
            {
                "name": "test-marketplace",
                "plugins": [{"name": "evil-plugin", "source": "../outside"}],
            },
            f,
        )

    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 0

    # Check that warning was logged
    assert any("escapes repository root" in record.message for record in caplog.records)


def test_dot_claude_detection(temp_dir):
    """Test detection of .claude/ directory with commands"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "commands").mkdir()

    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.DOT_CLAUDE
    assert len(context.plugins) == 1
    assert context.plugins[0].resolve() == claude_dir.resolve()


def test_dot_claude_direct(temp_dir):
    """Test linting .claude/ directory directly"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "skills").mkdir()

    context = RepositoryContext(claude_dir)
    assert context.repo_type == RepositoryType.DOT_CLAUDE
    assert len(context.plugins) == 1
    assert context.plugins[0].resolve() == claude_dir.resolve()


def test_dot_claude_skills_discovery(temp_dir):
    """Test that skills inside .claude/skills/ are discovered"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    skill_dir = claude_dir / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: Test\n---\n")

    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.DOT_CLAUDE
    assert len(context.skills) == 1
    assert context.skills[0].resolve() == skill_dir.resolve()


def test_plugins_file_not_detected_as_marketplace(temp_dir):
    """A regular file named 'plugins' should not be detected as a marketplace"""
    (temp_dir / "plugins").write_text("This is a plain file, not a directory")

    context = RepositoryContext(temp_dir)
    assert context.repo_type != RepositoryType.MARKETPLACE
    assert len(context.plugins) == 0


def test_dot_claude_not_detected_empty(temp_dir):
    """Empty .claude/ without marker dirs should not be DOT_CLAUDE"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()

    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.UNKNOWN


def test_detected_formats_empty(temp_dir):
    """Empty repo has no detected formats"""
    context = RepositoryContext(temp_dir)
    assert context.detected_formats == set()


def test_detected_formats_cursor_rules_dir(temp_dir):
    """Detect .cursor/rules/ directory"""
    (temp_dir / ".cursor" / "rules").mkdir(parents=True)
    context = RepositoryContext(temp_dir)
    assert HAS_CURSOR in context.detected_formats


def test_detected_formats_cursorrules_file(temp_dir):
    """Detect legacy .cursorrules file"""
    (temp_dir / ".cursorrules").write_text("some rules")
    context = RepositoryContext(temp_dir)
    assert HAS_CURSOR in context.detected_formats


def test_detected_formats_copilot(temp_dir):
    """Detect .github/copilot-instructions.md"""
    (temp_dir / ".github").mkdir()
    (temp_dir / ".github" / "copilot-instructions.md").write_text("# Instructions")
    context = RepositoryContext(temp_dir)
    assert HAS_COPILOT in context.detected_formats


def test_detected_formats_copilot_named_instructions_md(temp_dir):
    """Detect <name>.instructions.md files (e.g. coding.instructions.md)"""
    (temp_dir / ".github").mkdir()
    (temp_dir / ".github" / "coding.instructions.md").write_text("# Coding")
    context = RepositoryContext(temp_dir)
    assert HAS_COPILOT in context.detected_formats


def test_named_instructions_md_in_instruction_files(temp_dir):
    """Named .instructions.md files are collected in instruction_files for linting"""
    github_dir = temp_dir / ".github"
    github_dir.mkdir()
    coding = github_dir / "coding.instructions.md"
    coding.write_text("# Coding standards")
    testing = github_dir / "testing.instructions.md"
    testing.write_text("# Testing guidelines")

    context = RepositoryContext(temp_dir)

    names = [f.name for f in context.instruction_files]
    assert "coding.instructions.md" in names
    assert "testing.instructions.md" in names


def test_named_instructions_md_content_analysis(temp_dir):
    """Named .instructions.md files are included in content analysis"""
    from skillsaw.rules.builtin.content_analysis import gather_all_content_files

    github_dir = temp_dir / ".github"
    github_dir.mkdir()
    (github_dir / "coding.instructions.md").write_text("# Coding standards")

    context = RepositoryContext(temp_dir)
    files = gather_all_content_files(context)
    paths = [cf.path for cf in files]
    assert github_dir / "coding.instructions.md" in paths


def test_detected_formats_gemini(temp_dir):
    """Detect GEMINI.md at root"""
    (temp_dir / "GEMINI.md").write_text("# Gemini instructions")
    context = RepositoryContext(temp_dir)
    assert HAS_GEMINI in context.detected_formats


def test_detected_formats_agents_md(temp_dir):
    """Detect AGENTS.md at root"""
    (temp_dir / "AGENTS.md").write_text("# Agent instructions")
    context = RepositoryContext(temp_dir)
    assert HAS_AGENTS_MD in context.detected_formats


def test_detected_formats_kiro(temp_dir):
    """Detect .kiro/ directory"""
    (temp_dir / ".kiro").mkdir()
    context = RepositoryContext(temp_dir)
    assert HAS_KIRO in context.detected_formats


def test_detected_formats_claude_md(temp_dir):
    """Detect CLAUDE.md at root"""
    (temp_dir / "CLAUDE.md").write_text("# Claude instructions")
    context = RepositoryContext(temp_dir)
    assert HAS_CLAUDE_MD in context.detected_formats


def test_detected_formats_multiple(temp_dir):
    """Detect multiple formats in the same repo"""
    (temp_dir / "CLAUDE.md").write_text("# Claude")
    (temp_dir / "AGENTS.md").write_text("# Agents")
    (temp_dir / ".cursor" / "rules").mkdir(parents=True)
    context = RepositoryContext(temp_dir)
    assert HAS_CLAUDE_MD in context.detected_formats
    assert HAS_AGENTS_MD in context.detected_formats
    assert HAS_CURSOR in context.detected_formats
    assert HAS_COPILOT not in context.detected_formats


def test_apm_dir_with_dot_claude_not_dot_claude(temp_dir):
    """When .apm/ is present, .claude/ is compiled output — not DOT_CLAUDE"""
    apm_dir = temp_dir / ".apm"
    apm_dir.mkdir()
    (apm_dir / "instructions").mkdir()
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "commands").mkdir()
    context = RepositoryContext(temp_dir)
    # .claude/ is compiled output when .apm/ exists, so should NOT be DOT_CLAUDE
    assert context.repo_type != RepositoryType.DOT_CLAUDE


def test_apm_dir_with_skills_detected_as_agentskills(temp_dir):
    """.apm/ with SKILL.md is detected as both APM and AGENTSKILLS"""
    apm_dir = temp_dir / ".apm"
    apm_dir.mkdir()
    (apm_dir / "skills").mkdir()
    (temp_dir / "SKILL.md").write_text("---\nname: test\n---\n")
    context = RepositoryContext(temp_dir)
    assert RepositoryType.APM in context.repo_types
    assert RepositoryType.AGENTSKILLS in context.repo_types


def test_apm_dir_does_not_skip_format_detection(temp_dir):
    """.apm/ repos still detect instruction file formats normally"""
    apm_dir = temp_dir / ".apm"
    apm_dir.mkdir()
    (apm_dir / "instructions").mkdir()
    (temp_dir / "CLAUDE.md").write_text("# Instructions")
    (temp_dir / "GEMINI.md").write_text("# Instructions")
    (temp_dir / "AGENTS.md").write_text("# Instructions")
    context = RepositoryContext(temp_dir)
    assert HAS_CLAUDE_MD in context.detected_formats
    assert HAS_GEMINI in context.detected_formats
    assert HAS_AGENTS_MD in context.detected_formats


def test_apm_dir_does_not_override_marketplace(temp_dir):
    """Marketplace detection still takes priority over .apm/"""
    apm_dir = temp_dir / ".apm"
    apm_dir.mkdir()
    (apm_dir / "instructions").mkdir()
    claude_plugin = temp_dir / ".claude-plugin"
    claude_plugin.mkdir()
    (claude_plugin / "marketplace.json").write_text('{"name": "test", "plugins": []}')
    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.MARKETPLACE


# --- Multi-type detection tests ---


def test_multi_type_coderabbit_and_dot_claude(temp_dir):
    """Repo with both .coderabbit.yaml and .claude/ gets both CODERABBIT and DOT_CLAUDE types"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "commands").mkdir()
    (temp_dir / ".coderabbit.yaml").write_text("language: en-US\n")

    context = RepositoryContext(temp_dir)
    assert RepositoryType.CODERABBIT in context.repo_types
    assert RepositoryType.DOT_CLAUDE in context.repo_types
    # Primary type should be DOT_CLAUDE (higher priority than CODERABBIT)
    assert context.repo_type == RepositoryType.DOT_CLAUDE


def test_multi_type_coderabbit_and_marketplace(temp_dir):
    """Repo with .coderabbit.yaml and marketplace gets both types"""
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "marketplace.json").write_text('{"name": "test", "plugins": []}')
    (temp_dir / ".coderabbit.yaml").write_text("language: en-US\n")

    context = RepositoryContext(temp_dir)
    assert RepositoryType.CODERABBIT in context.repo_types
    assert RepositoryType.MARKETPLACE in context.repo_types
    # Primary type should be MARKETPLACE (highest priority)
    assert context.repo_type == RepositoryType.MARKETPLACE


def test_multi_type_coderabbit_alone(temp_dir):
    """Repo with only .coderabbit.yaml is just CODERABBIT"""
    (temp_dir / ".coderabbit.yaml").write_text("language: en-US\n")

    context = RepositoryContext(temp_dir)
    assert RepositoryType.CODERABBIT in context.repo_types
    assert RepositoryType.UNKNOWN not in context.repo_types
    assert context.repo_type == RepositoryType.CODERABBIT


def test_multi_type_repo_types_set(temp_dir):
    """repo_types is a set, repo_type is backward-compat property"""
    (temp_dir / "SKILL.md").write_text("---\nname: skill\ndescription: A skill\n---\n")
    (temp_dir / ".coderabbit.yaml").write_text("language: en-US\n")

    context = RepositoryContext(temp_dir)
    assert isinstance(context.repo_types, set)
    assert RepositoryType.AGENTSKILLS in context.repo_types
    assert RepositoryType.CODERABBIT in context.repo_types


def test_multi_type_unknown_only_when_empty(temp_dir):
    """UNKNOWN is only set when no other type matches"""
    context = RepositoryContext(temp_dir)
    assert context.repo_types == {RepositoryType.UNKNOWN}
    assert context.repo_type == RepositoryType.UNKNOWN


def test_multi_type_dot_claude_and_agentskills(temp_dir):
    """Repo with .claude/skills/ has both DOT_CLAUDE and AGENTSKILLS in repo_types"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    skill_dir = claude_dir / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: Test\n---\n")

    context = RepositoryContext(temp_dir)
    assert RepositoryType.DOT_CLAUDE in context.repo_types
    assert RepositoryType.AGENTSKILLS in context.repo_types
    # DOT_CLAUDE has higher priority than AGENTSKILLS for backward compat
    assert context.repo_type == RepositoryType.DOT_CLAUDE


def test_detected_formats_coderabbit(temp_dir):
    """Detect .coderabbit.yaml sets HAS_CODERABBIT format flag"""
    (temp_dir / ".coderabbit.yaml").write_text("language: en-US\n")
    context = RepositoryContext(temp_dir)
    assert HAS_CODERABBIT in context.detected_formats


def test_coderabbit_only_repo_gets_content_rules(temp_dir):
    """A coderabbit-only repo with instruction text should trigger content rules"""
    from skillsaw.config import LinterConfig
    from skillsaw.linter import Linter

    (temp_dir / ".coderabbit.yaml").write_text(
        "reviews:\n  instructions: |\n    Try to use consistent formatting.\n"
    )
    context = RepositoryContext(temp_dir)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()
    weak = [v for v in violations if v.rule_id == "content-weak-language"]
    assert len(weak) >= 1, "content-weak-language should fire on coderabbit instruction text"


def test_coderabbit_repo_no_command_violations(temp_dir):
    """A coderabbit-only repo should produce no command/skill violations"""
    from skillsaw.config import LinterConfig
    from skillsaw.linter import Linter

    (temp_dir / ".coderabbit.yaml").write_text("language: en-US\n")
    context = RepositoryContext(temp_dir)
    config = LinterConfig.default()
    linter = Linter(context, config)
    violations = linter.run()
    irrelevant = [
        v
        for v in violations
        if v.rule_id
        in {
            "command-naming",
            "command-frontmatter",
            "skill-frontmatter",
            "agent-frontmatter",
            "hooks-json-valid",
            "mcp-valid-json",
        }
    ]
    assert len(irrelevant) == 0, f"Should have no command/skill violations: {irrelevant}"


def test_coderabbit_with_claude_md_gets_both_formats(temp_dir):
    """Repo with both .coderabbit.yaml and CLAUDE.md has both format flags"""
    (temp_dir / ".coderabbit.yaml").write_text("language: en-US\n")
    (temp_dir / "CLAUDE.md").write_text("# Instructions\n")
    context = RepositoryContext(temp_dir)
    assert HAS_CODERABBIT in context.detected_formats
    assert HAS_CLAUDE_MD in context.detected_formats
