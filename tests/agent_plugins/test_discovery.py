"""Agent Plugins v1 repository detection and lint-tree routing."""

import json

from skillsaw.blocks import (
    AgentPluginMcpBlock,
    HooksBlock,
    McpBlock,
    SettingsBlock,
    SkillBlock,
    SkillRefBlock,
)
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import AgentPluginConfigNode, SkillNode

from ._helpers import MANIFEST_RULE, copy_fixture, lint_rules, messages_lower


class TestAgentPluginDetection:
    def test_canonical_root_manifest_detects_agent_plugin(self, tmp_path):
        repo = copy_fixture("agent-plugins/clean", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.AGENT_PLUGIN in context.repo_types
        assert context.repo_type is RepositoryType.AGENT_PLUGIN
        assert context.agent_plugins == [repo]
        nodes = context.lint_tree.find(AgentPluginConfigNode)
        assert [node.path for node in nodes] == [repo / "plugin.json"]
        blocks = context.lint_tree.find(AgentPluginMcpBlock)
        assert [node.path for node in blocks] == [repo / "mcp.json"]

    def test_only_immediate_skill_entrypoints_are_discovered(self, tmp_path):
        repo = copy_fixture("agent-plugins/clean", tmp_path)
        context = RepositoryContext(repo)

        names = [node.path.name for node in context.lint_tree.find(SkillNode)]
        assert names == ["release-audit"]
        skill_blocks = context.lint_tree.find(SkillBlock)
        assert [block.path for block in skill_blocks] == [
            repo / "skills" / "release-audit" / "SKILL.md"
        ]
        marker = "ignored/deeper"
        nested = [p for p in context.skills if marker in p.as_posix()]
        assert nested == []

    def test_immediate_plugin_children_detect_collection(self, tmp_path):
        repo = copy_fixture("agent-plugins/collection", tmp_path)
        canonical = repo / "plugins" / "canonical"
        context = RepositoryContext(repo)

        assert RepositoryType.AGENT_PLUGIN in context.repo_types
        assert context.agent_plugins == [canonical]
        nodes = context.lint_tree.find(AgentPluginConfigNode)
        assert [node.path for node in nodes] == [canonical / "plugin.json"]
        assert repo / "plugins" / "legacy" not in context.agent_plugins

    def test_legacy_root_manifest_is_not_schema_evidence(self, tmp_path):
        repo = copy_fixture("agent-plugins/legacy-root", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.AGENT_PLUGIN not in context.repo_types
        assert context.agent_plugins == []
        assert context.lint_tree.find(AgentPluginConfigNode) == []

    def test_mcp_without_manifest_does_not_activate_type(self, tmp_path):
        repo = copy_fixture("agent-plugins/mcp-only", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.AGENT_PLUGIN not in context.repo_types
        assert context.agent_plugins == []
        assert context.lint_tree.find(AgentPluginConfigNode) == []
        assert context.lint_tree.find(AgentPluginMcpBlock) == []

    def test_malformed_manifest_with_schema_is_detected(self, tmp_path):
        repo = copy_fixture("agent-plugins/malformed-manifest", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.AGENT_PLUGIN in context.repo_types
        assert context.agent_plugins == [repo]
        nodes = context.lint_tree.find(AgentPluginConfigNode)
        assert [node.path for node in nodes] == [repo / "plugin.json"]

    def test_unsupported_version_is_detected_for_diagnostics(self, tmp_path):
        repo = copy_fixture("agent-plugins/unsupported-schema", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.AGENT_PLUGIN in context.repo_types
        assert context.agent_plugins == [repo]

    def test_external_manifest_is_not_detection_evidence(self, tmp_path):
        fixture = copy_fixture("agent-plugins/manifest-escape", tmp_path)
        repo = fixture / "repo"
        context = RepositoryContext(repo)

        assert RepositoryType.AGENT_PLUGIN not in context.repo_types
        assert context.agent_plugins == []

    def test_nested_schema_in_valid_json_is_not_detection_evidence(self, tmp_path):
        """A parseable manifest is judged solely by its top-level $schema.

        A schema URI nested under ``metadata`` must not claim the repository,
        and the misclaim must not swallow repo-wide skill discovery.
        """
        repo = copy_fixture("agent-plugins/legacy-nested-schema", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.AGENT_PLUGIN not in context.repo_types
        assert context.agent_plugins == []
        assert context.lint_tree.find(AgentPluginConfigNode) == []
        skill_paths = [block.path for block in context.lint_tree.find(SkillBlock)]
        assert repo / "examples" / "demo" / "SKILL.md" in skill_paths

    def test_malformed_manifest_prose_mention_is_not_detection_evidence(self, tmp_path):
        """The raw-content fallback needs the property spelling, not a URI
        merely mentioned in description text."""
        repo = copy_fixture("agent-plugins/malformed-prose-schema", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.AGENT_PLUGIN not in context.repo_types
        assert context.agent_plugins == []

    def test_symlinked_plugins_dir_is_not_discovered(self, tmp_path):
        """A plugins/ symlink escaping the lint root contributes no members."""
        outside = tmp_path / "outside" / "member"
        outside.mkdir(parents=True)
        (outside / "plugin.json").write_text(
            json.dumps(
                {
                    "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                    "name": "external-member",
                }
            ),
            encoding="utf-8",
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("# Plugin collection\n", encoding="utf-8")
        (repo / "plugins").symlink_to(tmp_path / "outside", target_is_directory=True)

        context = RepositoryContext(repo)

        assert context.agent_plugins == []
        assert RepositoryType.AGENT_PLUGIN not in context.repo_types

    def test_symlinked_collection_child_is_skipped_beside_real_sibling(self, tmp_path):
        """Per-child containment drops only the escaping member."""
        outside = tmp_path / "outside-member"
        outside.mkdir()
        (outside / "plugin.json").write_text(
            json.dumps(
                {
                    "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                    "name": "external-member",
                }
            ),
            encoding="utf-8",
        )
        repo = tmp_path / "repo"
        real = repo / "plugins" / "real"
        real.mkdir(parents=True)
        (real / "plugin.json").write_text(
            json.dumps(
                {
                    "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                    "name": "real-member",
                }
            ),
            encoding="utf-8",
        )
        (repo / "plugins" / "escaping").symlink_to(outside, target_is_directory=True)

        context = RepositoryContext(repo)

        assert context.agent_plugins == [real]
        assert RepositoryType.AGENT_PLUGIN in context.repo_types


class TestExplicitAgentPluginType:
    def test_forced_missing_manifest_does_not_attach_claude_configs(self, tmp_path):
        repo = copy_fixture("agent-plugins/missing", tmp_path)
        hooks = repo / "hooks"
        hooks.mkdir()
        (hooks / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
        (repo / "settings.json").write_text("{}", encoding="utf-8")

        context = RepositoryContext(
            repo,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )

        nodes = context.lint_tree.find(AgentPluginConfigNode)
        assert [node.path for node in nodes] == [repo / "plugin.json"]
        assert context.lint_tree.find(HooksBlock) == []
        assert context.lint_tree.find(SettingsBlock) == []

    def test_missing_manifest_is_reported_when_type_is_forced(self, tmp_path):
        repo = copy_fixture("agent-plugins/missing", tmp_path)
        findings = lint_rules(
            repo,
            MANIFEST_RULE,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )

        assert findings
        assert any(
            "plugin.json" in message and "missing" in message
            for message in messages_lower(findings)
        )

    def test_schema_less_manifest_is_reported_when_forced(self, tmp_path):
        repo = copy_fixture("agent-plugins/legacy-root", tmp_path)
        findings = lint_rules(
            repo,
            MANIFEST_RULE,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )

        assert findings
        assert any("schema" in message for message in messages_lower(findings))

    def test_external_manifest_symlink_is_rejected(self, tmp_path):
        fixture = copy_fixture("agent-plugins/manifest-escape", tmp_path)
        repo = fixture / "repo"
        assert (repo / "plugin.json").is_symlink()

        findings = lint_rules(
            repo,
            MANIFEST_RULE,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )

        assert findings
        location_words = ("outside", "within", "contain")

        def has_location(message):
            return any(word in message for word in location_words)

        all_messages = messages_lower(findings)
        matching = [msg for msg in all_messages if "plugin.json" in msg]
        assert any(has_location(message) for message in matching)

    def test_forced_type_validates_collection_members_without_root_error(self, tmp_path):
        """``--type agent-plugin`` on a plugins/* collection scans the members.

        Forcing the type on a repository whose packages live under plugins/*
        must validate each member instead of fabricating a "missing
        plugin.json" finding for the repository root.
        """
        repo = copy_fixture("agent-plugins/collection", tmp_path)
        context = RepositoryContext(
            repo,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )

        assert context.agent_plugins == [
            repo / "plugins" / "canonical",
            repo / "plugins" / "legacy",
        ]

        findings = lint_rules(
            repo,
            MANIFEST_RULE,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )
        assert all(finding.file_path != repo / "plugin.json" for finding in findings)
        # The member that could not self-identify is still validated.
        legacy_manifest = repo / "plugins" / "legacy" / "plugin.json"
        legacy_findings = [f for f in findings if f.file_path == legacy_manifest]
        assert legacy_findings
        assert any("schema" in message for message in messages_lower(legacy_findings))

    def test_forced_type_builds_node_for_codex_only_repo(self, tmp_path):
        repo = copy_fixture("agent-plugins/codex-only", tmp_path)
        context = RepositoryContext(
            repo,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )

        assert context.agent_plugins == [repo]
        nodes = context.lint_tree.find(AgentPluginConfigNode)
        assert [node.path for node in nodes] == [repo / "plugin.json"]

        findings = lint_rules(
            repo,
            MANIFEST_RULE,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )
        assert any(
            "plugin.json" in message and "missing" in message
            for message in messages_lower(findings)
        )


def test_declared_package_keeps_containment_under_override(tmp_path):
    fixture = copy_fixture("agent-plugins/skill-entry-escape", tmp_path)
    repo = fixture / "repo"
    context = RepositoryContext(
        repo,
        repo_types={RepositoryType.AGENTSKILLS},
    )

    assert context.repo_types == {RepositoryType.AGENTSKILLS}
    assert context.agent_plugins == []
    assert context.agent_plugin_roots() == [repo.resolve()]
    skill_nodes = context.lint_tree.find(SkillNode)
    skill_names = [node.path.name for node in skill_nodes]
    assert skill_names == ["valid"]
    assert [block.path for block in context.lint_tree.find(SkillBlock)] == [
        repo / "skills" / "valid" / "SKILL.md"
    ]
    assert [block.path for block in context.lint_tree.find(SkillRefBlock)] == [
        repo / "skills" / "valid" / "references" / "inside.md"
    ]


def test_root_package_keeps_repo_wide_skill_discovery(tmp_path):
    """A root Agent Plugins declaration must not swallow the repository walk.

    Only the package's skills/ component keeps fixed one-level semantics;
    SKILL.md directories elsewhere in the repository stay discovered, and
    skills/* entries are not duplicated between the two discovery paths.
    """
    repo = copy_fixture("agent-plugins/root-package-agentskills", tmp_path)
    context = RepositoryContext(repo)

    assert RepositoryType.AGENT_PLUGIN in context.repo_types
    assert RepositoryType.AGENTSKILLS in context.repo_types
    skill_paths = [block.path for block in context.lint_tree.find(SkillBlock)]
    assert repo / "examples" / "demo" / "SKILL.md" in skill_paths
    assert repo / "skills" / "release-audit" / "SKILL.md" in skill_paths
    assert repo / "skills" / "ignored" / "deeper" / "SKILL.md" not in skill_paths
    assert len(skill_paths) == 2
    assert len(context.skills) == len(set(context.skills)) == 2


def test_dual_ecosystem_keeps_both_types_without_duplicate_skills(tmp_path):
    repo = copy_fixture("agent-plugins/dual-ecosystem", tmp_path)
    context = RepositoryContext(repo)

    assert RepositoryType.AGENT_PLUGIN in context.repo_types
    assert RepositoryType.SINGLE_PLUGIN in context.repo_types
    assert context.agent_plugins == [repo]
    assert len(context.lint_tree.find(AgentPluginConfigNode)) == 1
    assert {node.path.name for node in context.lint_tree.find(SkillNode)} == {
        "deeper",
        "release-audit",
    }
    assert len(context.lint_tree.find(SkillBlock)) == 2


def test_codex_and_agent_share_content_without_duplicates(tmp_path):
    repo = copy_fixture("agent-plugins/dual-codex", tmp_path)
    skill_file = repo / "skills" / "release-audit" / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace(
            "name: release-audit",
            "name: wrong-name",
        ),
        encoding="utf-8",
    )
    context = RepositoryContext(repo)

    assert RepositoryType.AGENT_PLUGIN in context.repo_types
    assert RepositoryType.CODEX_PLUGIN in context.repo_types
    assert context.agent_plugins == [repo]
    assert context.codex_plugins == [repo]
    assert len(context.lint_tree.find(AgentPluginConfigNode)) == 1
    skill_nodes = context.lint_tree.find(SkillNode)
    skill_names = [node.path.name for node in skill_nodes]
    assert skill_names == ["release-audit"]
    assert len(context.lint_tree.find(SkillBlock)) == 1
    assert len(lint_rules(repo, "agentskill-name")) == 1


def test_codex_and_agent_plugin_share_one_mcp_policy_surface(tmp_path):
    repo = copy_fixture("agent-plugins/dual-codex", tmp_path)
    context = RepositoryContext(repo)

    blocks = context.lint_tree.find(McpBlock)
    assert len(blocks) == 1
    assert isinstance(blocks[0], AgentPluginMcpBlock)
    assert blocks[0].path == repo / "mcp.json"

    findings = lint_rules(repo, "mcp-prohibited")
    assert len(findings) == 1
    assert findings[0].file_path == repo / "mcp.json"
