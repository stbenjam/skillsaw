"""Regression coverage for OpenAI ``agents/openai.yaml`` metadata."""

import json
from pathlib import Path

import pytest

from skillsaw.blocks import OpenAIMetadataBlock
from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.agentskills import AgentSkillUnreferencedFilesRule
from skillsaw.rules.builtin.codex import CodexOpenAIMetadataRule


def _write_codex_plugin(root: Path) -> Path:
    plugin = root / "demo-plugin"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo-plugin",
                "version": "1.0.0",
                "description": "OpenAI metadata test plugin",
                "skills": "./skills",
            }
        ),
        encoding="utf-8",
    )
    return plugin


def _write_skill(root: Path, name: str = "demo-skill") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: OpenAI metadata test skill\n---\n",
        encoding="utf-8",
    )
    return skill


def _write_metadata(owner: Path, body: str) -> Path:
    metadata = owner / "agents" / "openai.yaml"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(body, encoding="utf-8")
    return metadata


def _check(root: Path):
    return CodexOpenAIMetadataRule({}).check(RepositoryContext(root))


def test_discovers_plugin_and_embedded_skill_metadata(tmp_path):
    plugin = _write_codex_plugin(tmp_path)
    skill = _write_skill(plugin / "skills")
    plugin_metadata = _write_metadata(plugin, "interface:\n  display_name: Demo Plugin\n")
    skill_metadata = _write_metadata(skill, "interface:\n  display_name: Demo Skill\n")

    blocks = RepositoryContext(plugin).lint_tree.find(OpenAIMetadataBlock)

    assert {block.path for block in blocks} == {plugin_metadata, skill_metadata}
    plugin_block = next(block for block in blocks if block.path == plugin_metadata)
    skill_block = next(block for block in blocks if block.path == skill_metadata)
    assert plugin_block.metadata_root == plugin
    assert plugin_block.containment_root == plugin
    assert skill_block.metadata_root == skill
    assert skill_block.containment_root == plugin


def test_discovers_metadata_for_standalone_agent_skill(tmp_path):
    skill = _write_skill(tmp_path)
    metadata = _write_metadata(skill, "interface:\n  display_name: Standalone\n")

    blocks = RepositoryContext(skill).lint_tree.find(OpenAIMetadataBlock)

    assert [block.path for block in blocks] == [metadata]
    assert blocks[0].metadata_root == skill
    assert blocks[0].containment_root == skill


def test_accepts_every_documented_metadata_field_type(tmp_path):
    skill = _write_skill(tmp_path)
    (skill / "assets").mkdir()
    (skill / "assets" / "small.svg").write_text("<svg/>", encoding="utf-8")
    (skill / "assets" / "large.png").write_bytes(b"png")
    _write_metadata(
        skill,
        "interface:\n"
        "  display_name: Demo Skill\n"
        "  short_description: Route requests to the right tool\n"
        "  icon_small: ./assets/small.svg\n"
        "  icon_large: ./assets/large.png\n"
        '  brand_color: "#0F6CBD"\n'
        "  default_prompt: Route this request\n"
        "policy:\n"
        "  allow_implicit_invocation: true\n"
        "dependencies:\n"
        "  tools:\n"
        "    - type: mcp\n"
        "      value: research-server\n"
        "      description: Search the research corpus\n"
        "      transport: streamable_http\n"
        "      url: https://example.test/mcp\n",
    )

    assert _check(skill) == []


@pytest.mark.parametrize(
    "field, value",
    [
        ("display_name", "[Demo]"),
        ("short_description", "[Short]"),
        ("icon_small", "123"),
        ("icon_large", "false"),
        ("brand_color", "[red]"),
        ("default_prompt", "{prompt: demo}"),
    ],
)
def test_interface_fields_must_be_strings_with_line_attribution(tmp_path, field, value):
    skill = _write_skill(tmp_path)
    metadata = _write_metadata(skill, f"interface:\n  {field}: {value}\n")

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].file_path == metadata
    assert violations[0].line == 2
    assert violations[0].message == f"'interface.{field}' must be a string"


@pytest.mark.parametrize("value", ["red", "#FFF", "#12345G", "FF584A", "#ff584a55"])
def test_brand_color_must_be_rrggbb_hex(tmp_path, value):
    """OpenAI's bundled validator rejects anything but #RRGGBB — clean
    metadata here that the platform refuses to load is a false negative."""
    skill = _write_skill(tmp_path)
    metadata = _write_metadata(skill, f'interface:\n  brand_color: "{value}"\n')

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].file_path == metadata
    assert violations[0].line == 2
    assert "must be a #RRGGBB hex color" in violations[0].message


@pytest.mark.parametrize("value", ["#FF584A", "#ff584a", "#0F6cbd"])
def test_valid_brand_colors_pass(tmp_path, value):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, f'interface:\n  brand_color: "{value}"\n')

    assert _check(skill) == []


@pytest.mark.parametrize(
    "body, message, line",
    [
        ("interface: []\n", "'interface' must be a mapping", 1),
        ("policy: []\n", "'policy' must be a mapping", 1),
        ("dependencies: []\n", "'dependencies' must be a mapping", 1),
    ],
)
def test_documented_sections_must_be_mappings(tmp_path, body, message, line):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, body)

    violations = _check(skill)

    assert [(v.message, v.line) for v in violations] == [(message, line)]


@pytest.mark.parametrize("body", ["", "# nothing yet\n", "---\n"])
def test_an_empty_document_is_not_an_error(tmp_path, body):
    """An empty openai.yaml declares nothing — there is no metadata to
    validate and nothing Codex would reject."""
    skill = _write_skill(tmp_path)
    _write_metadata(skill, body)

    assert _check(skill) == []


def test_installed_plugin_metadata_stands_down(tmp_path):
    """Vendor content under .codex/plugins/ is diagnostic-only for every
    authored-manifest rule; this one follows the same line."""
    plugin = tmp_path / ".codex" / "plugins" / "vendor"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vendor", "version": "1.0.0", "description": "Vendor."}),
        encoding="utf-8",
    )
    _write_metadata(plugin, "interface:\n  brand_color: red\n  display_name: [Bad]\n")

    assert CodexOpenAIMetadataRule({}).check(RepositoryContext(tmp_path)) == []


def test_authored_plugin_metadata_still_fires(tmp_path):
    """The stand-down is provenance-scoped, not a blanket exemption."""
    plugin = _write_codex_plugin(tmp_path)
    _write_metadata(plugin, "interface:\n  brand_color: red\n")

    violations = CodexOpenAIMetadataRule({}).check(RepositoryContext(plugin))
    assert any("brand_color" in v.message for v in violations)


@pytest.mark.parametrize(
    ("body", "line"),
    [
        # A container root carries a ruamel position; a plain scalar does
        # not, and the line must then be omitted rather than fabricated.
        ("[]\n", 1),
        ("- entry\n", 1),
        ("plain text\n", None),
        ("42\n", None),
    ],
)
def test_document_root_must_be_a_mapping(tmp_path, body, line):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, body)

    violations = _check(skill)

    assert [(v.message, v.line) for v in violations] == [
        ("openai.yaml must be a YAML mapping", line)
    ]


def test_malformed_yaml_reports_the_parser_line(tmp_path):
    skill = _write_skill(tmp_path)
    metadata = _write_metadata(
        skill,
        "interface:\n  display_name: Demo\n  icon_small: [\n",
    )

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].file_path == metadata
    assert violations[0].message.startswith("Invalid YAML:")
    # libyaml reports the point where it expected the closing bracket: EOF.
    assert violations[0].line == 4


def test_valid_small_and_large_icon_paths_are_relative_to_owner(tmp_path):
    skill = _write_skill(tmp_path)
    (skill / "assets").mkdir()
    (skill / "assets" / "small.svg").write_text("<svg/>", encoding="utf-8")
    (skill / "assets" / "large.png").write_bytes(b"png")
    _write_metadata(
        skill,
        "interface:\n" "  icon_small: ./assets/small.svg\n" "  icon_large: assets/large.png\n",
    )

    assert _check(skill) == []


def test_missing_icon_is_a_line_attributed_warning(tmp_path):
    skill = _write_skill(tmp_path)
    metadata = _write_metadata(skill, "interface:\n  icon_small: ./assets/missing.svg\n")

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].file_path == metadata
    assert violations[0].line == 2
    assert violations[0].severity is Severity.WARNING
    assert "does not point to a bundled file" in violations[0].message


def test_empty_icon_path_is_rejected(tmp_path):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, "interface:\n  icon_small: '  '\n")

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].line == 2
    assert "is an empty path" in violations[0].message


@pytest.mark.parametrize(
    "icon",
    ["/tmp/logo.png", "C:\\logo.png", "\\\\server\\logo.png", "C:icon.png", "\\icon.png"],
)
def test_absolute_icon_path_is_rejected(tmp_path, icon):
    skill = _write_skill(tmp_path)
    metadata = _write_metadata(skill, f"interface:\n  icon_large: '{icon}'\n")

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].file_path == metadata
    assert violations[0].line == 2
    assert "must be relative" in violations[0].message


def test_windows_separator_in_relative_icon_path_is_portable(tmp_path):
    skill = _write_skill(tmp_path)
    (skill / "assets").mkdir()
    (skill / "assets" / "icon.svg").write_text("<svg/>", encoding="utf-8")
    _write_metadata(skill, "interface:\n  icon_small: 'assets\\icon.svg'\n")

    assert _check(skill) == []


@pytest.mark.parametrize("icon", ["../outside.svg", "..\\outside.svg"])
def test_icon_path_cannot_escape_a_standalone_skill(tmp_path, icon):
    skill = _write_skill(tmp_path)
    (tmp_path / "outside.svg").write_text("<svg/>", encoding="utf-8")
    _write_metadata(skill, f"interface:\n  icon_small: '{icon}'\n")

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].line == 2
    assert "escapes the owning plugin or skill" in violations[0].message


def test_embedded_skill_may_reference_shared_plugin_asset(tmp_path):
    plugin = _write_codex_plugin(tmp_path)
    skill = _write_skill(plugin / "skills")
    (plugin / "assets").mkdir()
    (plugin / "assets" / "shared.svg").write_text("<svg/>", encoding="utf-8")
    _write_metadata(skill, "interface:\n  icon_small: ../../assets/shared.svg\n")

    assert _check(plugin) == []


def test_icon_symlink_cannot_escape_the_owner(tmp_path):
    skill = _write_skill(tmp_path)
    outside = tmp_path / "outside.svg"
    outside.write_text("<svg/>", encoding="utf-8")
    (skill / "assets").mkdir()
    (skill / "assets" / "linked.svg").symlink_to(outside)
    _write_metadata(skill, "interface:\n  icon_small: ./assets/linked.svg\n")

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].line == 2
    assert "escapes the owning plugin or skill" in violations[0].message


def test_metadata_symlink_cannot_pull_an_external_file_into_the_tree(tmp_path):
    skill = _write_skill(tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text("interface:\n  display_name: External\n", encoding="utf-8")
    agents = skill / "agents"
    agents.mkdir()
    (agents / "openai.yaml").symlink_to(outside)

    assert RepositoryContext(skill).lint_tree.find(OpenAIMetadataBlock) == []


def test_shared_contained_metadata_is_validated_for_each_skill_owner(tmp_path):
    plugin = _write_codex_plugin(tmp_path)
    shared = plugin / "shared-openai.yaml"
    shared.write_text("interface:\n  icon_small: ./assets/icon.svg\n", encoding="utf-8")
    skills = [_write_skill(plugin / "skills", name) for name in ("first", "second")]
    for skill in skills:
        (skill / "assets").mkdir()
        (skill / "assets" / "icon.svg").write_text("<svg/>", encoding="utf-8")
        agents = skill / "agents"
        agents.mkdir()
        (agents / "openai.yaml").symlink_to(shared)

    blocks = RepositoryContext(plugin).lint_tree.find(OpenAIMetadataBlock)

    assert len(blocks) == 2
    assert {block.metadata_root for block in blocks} == set(skills)
    assert _check(plugin) == []


@pytest.mark.parametrize("allowed", [True, False])
def test_policy_accepts_both_boolean_values(tmp_path, allowed):
    skill = _write_skill(tmp_path)
    _write_metadata(
        skill,
        f"policy:\n  allow_implicit_invocation: {str(allowed).lower()}\n",
    )

    assert _check(skill) == []


def test_policy_rejects_a_non_boolean_with_line_attribution(tmp_path):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, 'policy:\n  allow_implicit_invocation: "true"\n')

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].line == 2
    assert "must be true or false" in violations[0].message


@pytest.mark.parametrize(
    "tools",
    [
        "[]",
        "[{type: mcp}]",
        (
            "[{type: mcp, value: server, description: Demo, "
            "transport: stdio, url: 'https://example.test/mcp'}]"
        ),
    ],
)
def test_dependencies_tools_accepts_documented_array_shapes(tmp_path, tools):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, f"dependencies:\n  tools: {tools}\n")

    assert _check(skill) == []


def test_dependencies_tools_must_be_an_array(tmp_path):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, "dependencies:\n  tools: mcp\n")

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].line == 2
    assert "must be an array" in violations[0].message


def test_each_dependency_tool_must_be_a_mapping(tmp_path):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, "dependencies:\n  tools:\n    - mcp\n")

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].line == 3
    assert "tools[0]' must be a mapping" in violations[0].message


@pytest.mark.parametrize("field", ["type", "value", "description", "transport", "url"])
def test_dependency_tool_fields_must_be_strings(tmp_path, field):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, f"dependencies:\n  tools:\n    - {field}: []\n")

    violations = _check(skill)

    assert len(violations) == 1
    assert violations[0].line == 3
    assert violations[0].message == f"'dependencies.tools[0].{field}' must be a string"


def test_unknown_metadata_keys_are_forward_compatible(tmp_path):
    skill = _write_skill(tmp_path)
    _write_metadata(
        skill,
        "future_top_level: true\n"
        "interface:\n  future_interface: {nested: value}\n"
        "policy:\n  future_policy: enabled\n"
        "dependencies:\n  tools:\n    - future_tool_key: [one, two]\n",
    )

    assert _check(skill) == []


def test_global_exclusion_prevents_metadata_discovery(tmp_path):
    skill = _write_skill(tmp_path)
    _write_metadata(skill, "interface:\n  display_name: Excluded\n")

    context = RepositoryContext(skill, exclude_patterns=["**/agents/openai.yaml"])

    assert context.lint_tree.find(OpenAIMetadataBlock) == []
    assert CodexOpenAIMetadataRule({}).check(context) == []


def test_excluded_metadata_does_not_make_its_icon_reachable(tmp_path):
    skill = _write_skill(tmp_path)
    (skill / "assets").mkdir()
    icon = skill / "assets" / "icon.svg"
    icon.write_text("<svg/>", encoding="utf-8")
    _write_metadata(skill, "interface:\n  icon_small: ./assets/icon.svg\n")
    context = RepositoryContext(skill, exclude_patterns=["**/agents/openai.yaml"])

    violations = AgentSkillUnreferencedFilesRule({}).check(context)

    assert icon in {violation.file_path for violation in violations}


def test_metadata_and_icons_are_reachable_but_an_orphan_remains_reported(tmp_path):
    skill = _write_skill(tmp_path)
    (skill / "assets").mkdir()
    small = skill / "assets" / "small.svg"
    large = skill / "assets" / "large.png"
    orphan = skill / "assets" / "orphan.txt"
    small.write_text("<svg/>", encoding="utf-8")
    large.write_bytes(b"png")
    orphan.write_text("not referenced", encoding="utf-8")
    _write_metadata(
        skill,
        "interface:\n" "  icon_small: ./assets/small.svg\n" "  icon_large: ./assets/large.png\n",
    )

    violations = AgentSkillUnreferencedFilesRule({}).check(RepositoryContext(skill))

    assert [violation.file_path for violation in violations] == [orphan]
