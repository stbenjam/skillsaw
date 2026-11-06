"""Codex 0.162.1 selection and raw-byte loader regressions."""

import json
import shutil
from pathlib import Path

import pytest

from skillsaw.blocks import (
    AgentBlock,
    AgentsMdBlock,
    CodexConfigBlock,
    CodexHooksBlock,
    CodexInstructionBlock,
    CommandBlock,
    ContentBlock,
    ExtraBlock,
    InstructionBlock,
    PluginRuleBlock,
    ReadmeBlock,
)
from skillsaw.codex_instructions import CodexInstructionFileNode, CodexInstructionsNode
from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.discovery.codex_instructions import select_instructions
from skillsaw.formats.codex_instructions import CodexInstructionOptions, instruction_bytes
from skillsaw.linter import Linter
from skillsaw.lint_target import LintTarget
from skillsaw.rule import Severity
from skillsaw.rules.builtin.instructions import InstructionFileValidRule
from tests.cli_runner import run_cli


def project(tmp_path, files, **options):
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    context = RepositoryContext(root, codex_instructions=CodexInstructionOptions(**options))
    return context, context.lint_tree.find(CodexInstructionsNode)[0].report(context.lint_tree)


@pytest.mark.parametrize("empty", [b"", b" \r\n\t", "\u2003"])
def test_empty_override_shadows_standard_and_fallback_without_charge(tmp_path, empty):
    _, report = project(
        tmp_path,
        {
            "AGENTS.override.md": empty,
            "AGENTS.md": "not selected",
            "TEAM.md": "not selected either",
            "child/AGENTS.md": "child",
        },
        cwd="child",
        project_doc_fallback_filenames=("TEAM.md",),
    )
    assert [e["path"] for e in report["selected"]] == ["AGENTS.override.md", "child/AGENTS.md"]
    assert [e["status"] for e in report["selected"]] == ["empty", "loaded"]
    assert report["charged_bytes"] == 5
    assert report["separator_bytes"] == 0


def test_fallback_order_empty_standard_and_directory_candidates(tmp_path):
    context, report = project(
        tmp_path,
        {
            "AGENTS.override.md/directory.txt": "not a regular file",
            "AGENTS.md": "",
            "TEAM.md": "shadowed",
            "child/SECOND.md": "second choice",
            "child/FIRST.md": "first choice",
        },
        cwd="child",
        project_doc_fallback_filenames=("FIRST.md", "SECOND.md"),
    )
    assert [e["path"] for e in report["selected"]] == ["AGENTS.md", "child/FIRST.md"]
    assert any(b.path.name == "FIRST.md" for b in context.lint_tree.find(ContentBlock))


@pytest.mark.parametrize("config_name", [None, "hooks.json", "config.toml"])
def test_selected_plugin_readme_keeps_display_owner_and_one_instruction_role(tmp_path, config_name):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/single-plugin/clean", root)
    (root / "child").mkdir()
    (root / "child/README.md").symlink_to("../README.md")
    if config_name:
        (root / ".codex").mkdir()
        (root / ".codex" / config_name).symlink_to("../README.md")
    context = RepositoryContext(
        root,
        codex_instructions=CodexInstructionOptions(
            cwd="child", project_doc_fallback_filenames=("README.md",)
        ),
    )
    tree = context.lint_tree
    readme = tree.find(ReadmeBlock)[0]
    instructions = tree.find(CodexInstructionBlock)
    assert len(instructions) == 1
    assert instructions[0].path == readme.path == root / "README.md"
    assert instructions[0].parent is readme.parent
    assert instructions[0].plugin_owner == readme.plugin_owner == root
    assert instructions[0].category == "agents-md"
    report = tree.find(CodexInstructionsNode)[0].report(tree)
    # The Markdown README cannot parse as TOML, but keeps its prose role.
    assert report["complete"] is (config_name != "config.toml")
    assert [entry["path"] for entry in report["selected"]] == ["README.md", "child/README.md"]
    expected_bytes = (
        None if config_name == "config.toml" else 2 * (root / "README.md").stat().st_size
    )
    assert report["charged_bytes"] == expected_bytes


@pytest.mark.parametrize("path_source", ["content_paths", "plugin_content_paths"])
@pytest.mark.parametrize("alias", [False, True])
def test_selected_fallback_replaces_generic_extra_role(tmp_path, path_source, alias):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/codex-instructions/other-host", root)
    path = root / "TEAM.md"
    (root / "AGENTS.override.md").rename(path)
    extra_path = path
    if alias:
        extra_path = root / "NOTES.md"
        extra_path.symlink_to(path.name)
    context = RepositoryContext(
        root,
        codex_instructions=CodexInstructionOptions(project_doc_fallback_filenames=(path.name,)),
    )
    setattr(context, path_source, [extra_path.name])
    tree = context.lint_tree
    assert not context.lint_tree_errors
    assert not tree.find(ExtraBlock)
    instructions = tree.find(CodexInstructionBlock)
    assert len(instructions) == 1
    assert instructions[0].path == path
    assert instructions[0].category == "agents-md"
    assert len([b for b in tree.find(ContentBlock) if b.path.resolve() == path]) == 1
    report = tree.find(CodexInstructionsNode)[0].report(tree)
    assert report["complete"]
    assert report["charged_bytes"] == path.stat().st_size


@pytest.mark.parametrize("filename", ["AGENTS.override.md", "TEAM.md"])
@pytest.mark.parametrize("projected", [False, True])
@pytest.mark.parametrize("alias", [False, True])
def test_codex_instruction_keeps_configured_opencode_role(tmp_path, filename, projected, alias):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/codex-instructions/other-host", root)
    path = root / filename
    (root / "AGENTS.override.md").rename(path)
    configured_path = path
    if alias:
        configured_path = root / "guidance.md"
        configured_path.symlink_to(path.name)
    (root / "opencode.json").write_text(json.dumps({"instructions": [configured_path.name]}))
    options = (
        CodexInstructionOptions(project_doc_fallback_filenames=(filename,)) if projected else None
    )
    context = RepositoryContext(root, codex_instructions=options)
    tree = context.lint_tree
    blocks = [block for block in tree.find(ContentBlock) if block.resolved_path == path]
    assert len(blocks) == 1
    block = blocks[0]
    assert type(block) is InstructionBlock
    assert block.path == configured_path
    assert block.category == "instruction"
    validation = block.find(CodexInstructionFileNode)
    assert len(validation) == int(projected or filename == "AGENTS.override.md")
    if validation:
        assert validation[0].parent is block
    if projected:
        report = tree.find(CodexInstructionsNode)[0].report(tree)
        assert report["complete"]
        assert [entry["path"] for entry in report["selected"]] == [filename]
        assert report["charged_bytes"] == path.stat().st_size


@pytest.mark.parametrize("custom_role", [False, True])
@pytest.mark.parametrize("lint_external", [False, True])
@pytest.mark.parametrize("config_name", [None, "hooks.json", "config.toml"])
def test_selected_fallback_retains_contributor_metadata_and_semantic_roles(
    tmp_path, custom_role, lint_external, config_name
):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/codex-instructions/other-host", root)
    path = root / "TEAM.md"
    (root / "AGENTS.override.md").rename(path)
    if config_name:
        (root / ".codex").mkdir()
        (root / ".codex" / config_name).symlink_to("../TEAM.md")

    class CustomProse(ExtraBlock):
        pass

    block_type = CustomProse if custom_role else ExtraBlock
    child = LintTarget(path=root / "notes.txt")
    child.path.write_text("Contributor metadata reference.\n")
    original = block_type(
        path=path,
        plugin_owner=root,
        children=[child],
        content_suppressed=True,
        externally_sourced=True,
    )
    context = RepositoryContext(
        root,
        codex_instructions=CodexInstructionOptions(project_doc_fallback_filenames=(path.name,)),
        lint_external_content=lint_external,
    )
    context.plugin_tree_contributors = [("extra-prose", lambda _context, _tree: [original])]
    tree = context.lint_tree
    assert not context.lint_tree_errors
    assert not context.plugin_extension_errors
    blocks = [b for b in tree.find(ContentBlock) if b.path == path]
    if not lint_external:
        assert blocks == []
        assert child not in list(tree.walk())
        return
    assert len(blocks) == 1
    block = blocks[0]
    assert type(block) is (CustomProse if custom_role else CodexInstructionBlock)
    assert block.plugin_owner == root
    assert block.content_suppressed
    assert block.externally_sourced
    assert child in block.children
    validation = block.find(CodexInstructionFileNode)
    assert len(validation) == int(custom_role)
    if validation:
        assert validation[0].parent is block
        assert validation[0].in_suppressed_content
        assert validation[0].in_external_source
    assert child.parent is block
    assert child.in_external_source
    if config_name:
        config_type = CodexHooksBlock if config_name == "hooks.json" else CodexConfigBlock
        assert len([node for node in tree.find(config_type) if node.resolved_path == path]) == 1


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("lint_external", [False, True])
@pytest.mark.parametrize("excluded", [False, True])
@pytest.mark.parametrize("filename", ["TEAM.md", "AGENTS.override.md"])
def test_selected_file_validation_respects_prose_roles_and_pruning(
    tmp_path, structured, lint_external, excluded, filename
):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/codex-instructions/other-host", root)
    path = root / filename
    (root / "AGENTS.override.md").rename(path)
    path.write_bytes(b"\xff")

    class CustomProse(ExtraBlock):
        pass

    block_type = CodexConfigBlock if structured else CustomProse
    original = block_type(path=path, plugin_owner=root, externally_sourced=True)
    context = RepositoryContext(
        root,
        codex_instructions=(
            CodexInstructionOptions(project_doc_fallback_filenames=(path.name,))
            if filename == "TEAM.md"
            else None
        ),
        lint_external_content=lint_external,
        exclude_patterns=[path.name] if excluded else [],
    )
    context.plugin_tree_contributors = [("semantic-role", lambda _context, _tree: [original])]
    found = InstructionFileValidRule().check(context)
    assert len(found) == int(not structured and lint_external and not excluded)
    if found:
        assert found[0].file_path == path
        assert f"Failed to read {filename}" in found[0].message
    assert not context.lint_tree_errors
    assert not context.plugin_extension_errors


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("filename", ["TEAM.md", "AGENTS.override.md"])
@pytest.mark.parametrize("excluded", [False, True])
def test_selected_semantic_source_aliases_are_validated_once(
    tmp_path, selected, filename, excluded
):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/single-plugin/clean", root)
    path = root / "commands/status.md"
    path.write_text("")
    (root / "child").mkdir()
    (root / filename).symlink_to("commands/status.md")
    (root / "child" / filename).symlink_to("../commands/status.md")
    context = RepositoryContext(
        root,
        codex_instructions=(
            CodexInstructionOptions(cwd="child", project_doc_fallback_filenames=(filename,))
            if selected
            else None
        ),
        exclude_patterns=["commands/status.md"] if excluded else [],
    )
    found = InstructionFileValidRule().check(context)
    expected = (selected or filename == "AGENTS.override.md") and not excluded
    assert len(found) == int(expected)
    if expected:
        assert found[0].file_path == path
        assert found[0].message == "status.md is empty"
    commands = [b for b in context.lint_tree.find(CommandBlock) if b.path == path]
    assert len(commands) == int(not excluded)
    if commands:
        assert commands[0].plugin_owner == root
    assert len(context.lint_tree.find(CodexInstructionFileNode)) == int(expected)


def test_semantic_override_validation_survives_frontmatter_rebuild(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/single-plugin/clean", root)
    path = root / "commands/status.md"
    (root / "AGENTS.override.md").symlink_to("commands/status.md")
    context = RepositoryContext(root)
    tree = context.lint_tree
    command = next(block for block in tree.find(CommandBlock) if block.path == path)
    assert len(tree.find(CodexInstructionFileNode)) == 1
    command.write_frontmatter_text("name: status\ndescription: Show repository status.\n")
    assert len(tree.find(CodexInstructionFileNode)) == 1
    assert tree.find(CodexInstructionFileNode)[0].parent is command
    assert InstructionFileValidRule().check(context) == []


@pytest.mark.parametrize("inspect", [False, True])
@pytest.mark.parametrize(
    "directory,block_type,plugin_location,ecosystem",
    [
        ("agents", AgentBlock, ".", "claude"),
        ("commands", CommandBlock, ".", "claude"),
        ("rules/nested", PluginRuleBlock, ".", "claude"),
        ("agents", AgentBlock, "plugins/tools", "dual"),
        ("commands", CommandBlock, "plugins/tools", "claude"),
        ("rules/nested", PluginRuleBlock, "plugins/tools", "codex"),
    ],
)
def test_override_keeps_plugin_prose_role(
    tmp_path, inspect, directory, block_type, plugin_location, ecosystem
):
    root = tmp_path / "repo"
    plugin = root / plugin_location
    shutil.copytree(Path(__file__).parent / "fixtures/single-plugin/clean", plugin)
    if ecosystem in {"codex", "dual"}:
        (plugin / ".codex-plugin").mkdir()
        (plugin / ".codex-plugin/plugin.json").write_text('{"name": "deployment-tools"}')
    if ecosystem == "codex":
        shutil.rmtree(plugin / ".claude-plugin")
    path = plugin / directory / "AGENTS.override.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plugin / "agents/reviewer.md", path)
    options = CodexInstructionOptions(cwd=str(path.parent.relative_to(root))) if inspect else None
    context = RepositoryContext(root, codex_instructions=options)
    tree = context.lint_tree
    blocks = [b for b in tree.find(block_type) if b.path == path]
    assert len(blocks) == 1
    assert blocks[0].plugin_owner == plugin.resolve()
    assert len([b for b in tree.find(ContentBlock) if b.path == path]) == 1
    assert not tree.find(CodexInstructionBlock)
    assert not context.lint_tree_errors
    if inspect:
        report = tree.find(CodexInstructionsNode)[0].report(tree)
        assert report["complete"]
        assert [entry["path"] for entry in report["selected"]] == [str(path.relative_to(root))]
        assert report["charged_bytes"] == path.stat().st_size


@pytest.mark.parametrize(
    "directory,block_type", [("agents", AgentBlock), ("commands", CommandBlock)]
)
def test_override_alias_keeps_canonical_plugin_role(tmp_path, directory, block_type):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/single-plugin/clean", root)
    target = root / directory / ("reviewer.md" if directory == "agents" else "status.md")
    (root / "AGENTS.override.md").symlink_to(target.relative_to(root))
    context = RepositoryContext(root, codex_instructions=CodexInstructionOptions())
    tree = context.lint_tree
    assert any(b.path == target and b.plugin_owner == root for b in tree.find(block_type))
    assert len([b for b in tree.find(ContentBlock) if b.path.resolve() == target]) == 1
    assert not tree.find(CodexInstructionBlock)
    report = tree.find(CodexInstructionsNode)[0].report(tree)
    assert report["complete"]
    assert [entry["path"] for entry in report["selected"]] == ["AGENTS.override.md"]
    assert report["charged_bytes"] == target.stat().st_size


@pytest.mark.parametrize("inspect", [False, True])
@pytest.mark.parametrize("plugin_location", [".", "plugins/tools"])
@pytest.mark.parametrize("override_is_alias", [False, True])
def test_override_readme_alias_retains_prose_and_display(
    tmp_path, inspect, plugin_location, override_is_alias
):
    root = tmp_path / "repo"
    plugin = root / plugin_location
    shutil.copytree(Path(__file__).parent / "fixtures/single-plugin/clean", plugin)
    readme_path = plugin / "README.md"
    override = plugin / "AGENTS.override.md"
    if override_is_alias:
        override.symlink_to("README.md")
    else:
        readme_path.rename(override)
        readme_path.symlink_to("AGENTS.override.md")
    options = CodexInstructionOptions(cwd=plugin_location) if inspect else None
    context = RepositoryContext(root, codex_instructions=options)
    tree = context.lint_tree
    readme = tree.find(ReadmeBlock)[0]
    instructions = tree.find(CodexInstructionBlock)
    assert len(instructions) == 1
    instruction = instructions[0]
    assert instruction.path == override
    assert instruction.parent is readme.parent
    assert instruction.plugin_owner == readme.plugin_owner == plugin.resolve()
    assert instruction.content_suppressed == readme.content_suppressed
    assert instruction.externally_sourced == readme.externally_sourced
    assert len([b for b in tree.find(ContentBlock) if b.path.resolve() == override.resolve()]) == 1
    assert not context.lint_tree_errors
    if inspect:
        report = tree.find(CodexInstructionsNode)[0].report(tree)
        assert report["complete"]
        assert [entry["path"] for entry in report["selected"]] == [str(override.relative_to(root))]
        assert report["charged_bytes"] == override.stat().st_size


@pytest.mark.parametrize("inspect", [False, True])
@pytest.mark.parametrize("override_is_alias", [False, True])
@pytest.mark.parametrize(
    "suppressed,external,lint_external",
    [(True, False, True), (False, True, True), (True, True, True), (True, True, False)],
)
def test_override_readme_alias_inherits_contributor_metadata(
    tmp_path, inspect, override_is_alias, suppressed, external, lint_external
):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/single-plugin/clean", root)
    readme_path = root / "README.md"
    override = root / "AGENTS.override.md"
    if override_is_alias:
        override.symlink_to("README.md")
    else:
        readme_path.rename(override)
        readme_path.symlink_to("AGENTS.override.md")

    def tag_readme(_context, tree):
        readme = tree.find(ReadmeBlock)[0]
        readme.content_suppressed = suppressed
        readme.externally_sourced = external
        return []

    context = RepositoryContext(
        root,
        codex_instructions=CodexInstructionOptions() if inspect else None,
        lint_external_content=lint_external,
    )
    context.plugin_tree_contributors = [("readme-metadata", tag_readme)]
    tree = context.lint_tree
    assert not context.lint_tree_errors
    assert not context.plugin_extension_errors
    instructions = tree.find(CodexInstructionBlock)
    readmes = tree.find(ReadmeBlock)
    if external and not lint_external:
        assert instructions == []
        assert readmes == []
    else:
        assert len(instructions) == len(readmes) == 1
        instruction, readme = instructions[0], readmes[0]
        assert instruction.content_suppressed is suppressed
        assert instruction.externally_sourced is external
        assert instruction.plugin_owner == readme.plugin_owner == root
        assert instruction.parent is readme.parent
        assert len([b for b in tree.find(ContentBlock) if b.path == override]) == 1


def test_override_outside_plugin_glob_stays_instruction(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/single-plugin/clean", root)
    path = root / "commands/nested/AGENTS.override.md"
    path.parent.mkdir()
    shutil.copyfile(root / "agents/reviewer.md", path)
    context = RepositoryContext(root)
    instructions = context.lint_tree.find(CodexInstructionBlock)
    assert [b.path for b in instructions] == [path]
    assert instructions[0].plugin_owner is None
    assert not context.lint_tree_errors


def test_selected_configuration_fallback_does_not_gain_a_prose_role(tmp_path):
    context, report = project(
        tmp_path,
        {".codex/config.toml": "project_doc_max_bytes = 65536\n"},
        cwd=".codex",
        project_doc_fallback_filenames=("config.toml",),
    )
    assert report["complete"]
    assert [entry["path"] for entry in report["selected"]] == [".codex/config.toml"]
    assert len(context.lint_tree.find(CodexConfigBlock)) == 1
    assert not context.lint_tree.find(ContentBlock)


def test_root_to_cwd_excludes_siblings_deeper_and_above_root(tmp_path):
    (tmp_path / "AGENTS.md").write_text("outside scope")
    _, report = project(
        tmp_path,
        {
            "AGENTS.md": "root",
            "a/AGENTS.override.md": "override",
            "a/AGENTS.md": "shadowed",
            "a/b/AGENTS.md": "cwd",
            "a/b/deeper/AGENTS.md": "deeper",
            "sibling/AGENTS.md": "sibling",
        },
        cwd="a/b",
    )
    assert [e["path"] for e in report["selected"]] == [
        "AGENTS.md",
        "a/AGENTS.override.md",
        "a/b/AGENTS.md",
    ]
    assert report["charged_bytes"] == 15
    assert report["rendered_project_bytes"] == 19


@pytest.mark.parametrize(
    "data,limit,charged,text,status,truncated",
    [
        (b"hello", 5, 5, 5, "loaded", False),
        ("éé".encode(), 3, 3, 5, "truncated", True),
        ("😀".encode(), 1, 1, 3, "truncated", True),
        (b"\xc3", 64, 1, 3, "loaded", False),
        (b"\xe2\x80", 64, 2, 3, "loaded", False),
        (b"\xf0\x9f\x98", 64, 3, 3, "loaded", False),
        (b"policy \xe2\x80", 64, 9, 10, "loaded", False),
        (b"A\xffB", 3, 3, 5, "loaded", False),
        (b"\xef\xbb\xbfA\r\n", 6, 6, 6, "loaded", False),
        (b"   text", 3, 0, 0, "empty", True),
        ("\u2003\u00a0".encode(), 5, 0, 0, "empty", False),
        ("\u2003".encode(), 2, 2, 3, "truncated", True),
        (b"\x1c", 1, 1, 1, "loaded", False),
        (b"anything", 0, 0, 0, "omitted", False),
    ],
)
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 65536])
def test_raw_bytes_lossy_utf8_and_rust_whitespace(
    data, limit, charged, text, status, truncated, chunk_size
):
    chunks = (data[index : index + chunk_size] for index in range(0, len(data), chunk_size))
    result = instruction_bytes(chunks, limit, file_bytes=len(data))
    assert (result.charged_bytes, result.text_bytes, result.status, result.truncated) == (
        charged,
        text,
        status,
        truncated,
    )


def test_whitespace_prefix_does_not_exhaust_child_budget(tmp_path):
    _, report = project(
        tmp_path,
        {"AGENTS.md": "   hidden", "child/AGENTS.md": "child"},
        cwd="child",
        project_doc_max_bytes=3,
    )
    assert [e["charged_bytes"] for e in report["selected"]] == [0, 3]
    assert report["affected_paths"] == ["AGENTS.md", "child/AGENTS.md"]


def test_project_layers_merge_before_validation_and_apply_to_entire_chain(tmp_path):
    _, report = project(
        tmp_path,
        {
            ".codex/config.toml": 'project_doc_max_bytes = "shadowed"\nproject_doc_fallback_filenames = ["ROOT.md"]\n',
            "child/.codex/config.toml": 'project_doc_max_bytes = 7\nproject_doc_fallback_filenames = [" TEAM.md ", "TEAM.md", "AGENTS.md", "../outside.md", ""]\n',
            "TEAM.md": "root",
            "ROOT.md": "wrong",
            "child/TEAM.md": "abcdef",
        },
        cwd="child",
    )
    assert report["complete"]
    assert [e["path"] for e in report["selected"]] == ["TEAM.md", "child/TEAM.md"]
    assert [e["charged_bytes"] for e in report["selected"]] == [4, 3]
    assert report["candidate_filenames"] == ["AGENTS.override.md", "AGENTS.md", "TEAM.md"]
    assert report["ignored_fallback_filenames"] == ["../outside.md"]
    assert report["limit_source"] == "child/.codex/config.toml"
    assert report["rendered_project_bytes"] == 9


def test_explicit_inputs_override_local_config_and_empty_fallback_list(tmp_path):
    _, report = project(
        tmp_path,
        {
            ".codex/config.toml": 'project_doc_max_bytes = 1\nproject_doc_fallback_filenames = ["TEAM.md"]\n',
            "TEAM.md": "not selected",
            "child/AGENTS.md": "abcdef",
        },
        cwd="child",
        project_doc_max_bytes=65536,
        project_doc_fallback_filenames=(),
    )
    assert report["project_doc_max_bytes"] == 65536
    assert [e["path"] for e in report["selected"]] == ["child/AGENTS.md"]
    assert report["affected_paths"] == []


@pytest.mark.parametrize(
    "text",
    [
        "project_doc_max_bytes = -1",
        "project_doc_max_bytes = true",
        "project_doc_max_bytes = 9223372036854775808",
        "project_doc_max_bytes = -9223372036854775809",
        'project_doc_fallback_filenames = "TEAM.md"',
        "not valid toml = [",
    ],
)
def test_bad_local_config_is_incomplete(tmp_path, text):
    _, report = project(tmp_path, {".codex/config.toml": text, "AGENTS.md": "root"})
    assert not report["complete"]
    assert report["charged_bytes"] is None
    assert report["issues"]


@pytest.mark.parametrize("limit", [-(2**63) - 1, 2**63])
@pytest.mark.parametrize("explicit", [False, True])
def test_unparseable_byte_limit_cannot_be_shadowed(tmp_path, limit, explicit):
    files = {
        ".codex/config.toml": f"project_doc_max_bytes = {limit}\n",
        "child/AGENTS.md": "Run the package tests before committing.\n",
    }
    if not explicit:
        files["child/.codex/config.toml"] = "project_doc_max_bytes = 65536\n"
    _, report = project(
        tmp_path,
        files,
        cwd="child",
        project_doc_max_bytes=65536 if explicit else None,
    )
    assert not report["complete"]
    assert report["charged_bytes"] is None
    assert report["issues"] == [
        ".codex/config.toml: integer outside Codex's signed 64-bit TOML integer range in "
        "project_doc_max_bytes"
    ]


@pytest.mark.parametrize("limit", [-(2**63), -1])
@pytest.mark.parametrize("explicit", [False, True])
def test_parseable_negative_byte_limit_can_be_shadowed(tmp_path, limit, explicit):
    instructions = "Run the package tests before committing.\n"
    files = {
        ".codex/config.toml": f"project_doc_max_bytes = {limit}\n",
        "child/AGENTS.md": instructions,
    }
    if not explicit:
        files["child/.codex/config.toml"] = "project_doc_max_bytes = 65536\n"
    _, report = project(
        tmp_path,
        files,
        cwd="child",
        project_doc_max_bytes=65536 if explicit else None,
    )
    assert report["complete"]
    assert report["project_doc_max_bytes"] == 65536
    assert report["charged_bytes"] == len(instructions.encode("utf-8"))
    assert report["issues"] == []


@pytest.mark.parametrize("key", ["project_doc_max_bytes", "project_doc_fallback_filenames"])
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize(
    "raw,valid",
    [
        ("[9223372036854775808]", False),
        ("{ nested = [-9223372036854775809] }", False),
        ("[[], 9223372036854775808]", False),
        ("{ empty = [], later = [-9223372036854775809] }", False),
        ("[9223372036854775807]", True),
        ("{ nested = [-9223372036854775808] }", True),
        ("[[], 9223372036854775807]", True),
        ("{ empty = [], later = [-9223372036854775808] }", True),
    ],
)
def test_nested_integer_bounds_apply_before_setting_overrides(tmp_path, key, explicit, raw, valid):
    instructions = "Run the package tests before committing.\n"
    files = {
        ".codex/config.toml": f"{key} = {raw}\n",
        "child/AGENTS.md": instructions,
    }
    options = {}
    if explicit:
        options[key] = 65536 if key == "project_doc_max_bytes" else ("TEAM.md",)
    else:
        value = "65536" if key == "project_doc_max_bytes" else '["TEAM.md"]'
        files["child/.codex/config.toml"] = f"{key} = {value}\n"
    _, report = project(tmp_path, files, cwd="child", **options)
    assert report["complete"] is valid
    if valid:
        assert report["charged_bytes"] == len(instructions.encode("utf-8"))
        assert report["issues"] == []
        if key == "project_doc_max_bytes":
            assert report["project_doc_max_bytes"] == 65536
        else:
            assert report["candidate_filenames"] == ["AGENTS.override.md", "AGENTS.md", "TEAM.md"]
    else:
        assert report["charged_bytes"] is None
        assert report["issues"] == [
            ".codex/config.toml: integer outside Codex's signed 64-bit TOML integer range in " + key
        ]


@pytest.mark.parametrize("symlink", [False, True])
def test_exclusion_does_not_fall_through_to_standard(tmp_path, monkeypatch, symlink):
    context, _ = project(tmp_path, {"AGENTS.override.md": "override", "AGENTS.md": "standard"})
    override = context.root_path / "AGENTS.override.md"
    if symlink:
        override.rename(context.root_path / "private.txt")
        override.symlink_to("private.txt")
    original = Path.open
    forbidden_reads = []

    def scoped_open(path, *args, **kwargs):
        if path.resolve() == override.resolve():
            forbidden_reads.append(path)
            raise AssertionError(f"excluded read: {path}")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", scoped_open)
    context.exclude_patterns = ["private.txt" if symlink else "AGENTS.override.md"]
    context.apply_excludes()
    report = context.lint_tree.find(CodexInstructionsNode)[0].report(context.lint_tree)
    assert forbidden_reads == []
    assert not context.lint_tree_errors
    assert not report["complete"]
    assert [e["path"] for e in report["selected"]] == ["AGENTS.override.md"]


@pytest.mark.parametrize("symlink", [False, True])
def test_uninspectable_candidate_keeps_selection_unknown(tmp_path, monkeypatch, symlink):
    override = tmp_path / "AGENTS.override.md"
    if symlink:
        override.symlink_to("private.txt")
    else:
        override.write_text("Private instructions")
    (tmp_path / "AGENTS.md").write_text("Standard instructions")
    original = Path.stat if symlink else Path.lstat

    def fail_candidate(path, *args, **kwargs):
        if path == override and kwargs.get("follow_symlinks", True):
            raise PermissionError("candidate metadata is inaccessible")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat" if symlink else "lstat", fail_candidate)
    selected = select_instructions(
        (tmp_path,),
        ("AGENTS.override.md", "AGENTS.md"),
        resolve=lambda path: path,
        is_excluded=lambda path: False,
    )
    assert len(selected) == 1
    assert selected[0].path == override
    assert "cannot inspect file" in selected[0].issue


@pytest.mark.parametrize("symlink", [False, True])
def test_excluded_config_directory_is_never_read(tmp_path, monkeypatch, symlink):
    root = tmp_path / "repo"
    (root / ".codex").mkdir(parents=True)
    excluded = root / ("private" if symlink else ".codex")
    excluded.mkdir(exist_ok=True)
    (excluded / "config.toml").write_text("project_doc_max_bytes = 1")
    if symlink:
        (root / ".codex/config.toml").symlink_to("../private/config.toml")
    (root / "AGENTS.md").write_text("Repository instructions")
    original = Path.open
    forbidden_reads = []

    def scoped_open(path, *args, **kwargs):
        if path.resolve().is_relative_to(excluded):
            forbidden_reads.append(path)
            raise AssertionError(f"excluded read: {path}")
        return original(path, *args, **kwargs)

    context = RepositoryContext(
        root, exclude_patterns=[excluded.name], codex_instructions=CodexInstructionOptions()
    )
    monkeypatch.setattr(Path, "open", scoped_open)
    tree = context.lint_tree
    assert not tree.find(CodexConfigBlock)
    report = tree.find(CodexInstructionsNode)[0].report(tree)
    assert forbidden_reads == []
    assert not context.lint_tree_errors
    assert not report["complete"]
    assert report["project_doc_max_bytes"] == 32768
    assert report["charged_bytes"] is None
    assert "excluded" in report["issues"][0]


@pytest.mark.parametrize("symlink", [False, True])
def test_ordinary_override_discovery_never_reads_excluded_content(tmp_path, monkeypatch, symlink):
    root = tmp_path / "repo"
    excluded = root / (".codex" if symlink else "private")
    excluded.mkdir(parents=True)
    target = excluded / ("config.toml" if symlink else "AGENTS.override.md")
    target.write_text("project_doc_max_bytes = 1\n" if symlink else "Private guidance.\n" * 4000)
    if symlink:
        (root / "AGENTS.override.md").symlink_to(".codex/config.toml")
    (root / ".skillsaw.yaml").write_text("exclude: [" + excluded.name + "]\n")
    original = Path.open

    def scoped_open(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(excluded), f"excluded read: {path}"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", scoped_open)
    result = run_cli(["lint", root, "--rule", "context-budget", "--strict", "--format", "json"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["violations"] == []


@pytest.mark.parametrize("scope", ["included", "excluded-ancestor", "excluded-target", "escape"])
@pytest.mark.parametrize("config", [False, True])
def test_codex_detection_matches_attachment_scope(tmp_path, monkeypatch, scope, config):
    root = tmp_path / "repo"
    path = root / "service" / (".codex/config.toml" if config else "AGENTS.override.md")
    path.parent.mkdir(parents=True)
    target = path
    if scope == "excluded-target":
        target = root / ".private/guide.md"
        target.parent.mkdir()
        path.symlink_to(target)
    elif scope == "escape":
        target = tmp_path / "guide.md"
        path.symlink_to(target)
    target.write_text(
        "project_doc_max_bytes = 32768\n"
        if config
        else "# Service instructions\n\nRun the service tests before deployment.\n"
    )
    exclusions = {"excluded-ancestor": ["service"], "excluded-target": [".private"]}
    original = Path.open
    allow_read = scope == "included"
    forbidden_reads = []

    def scoped_open(file, *args, **kwargs):
        if not allow_read and file.resolve() == target.resolve():
            forbidden_reads.append(file)
            raise AssertionError(f"out-of-scope read: {file}")
        return original(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", scoped_open)
    context = RepositoryContext(root, exclude_patterns=exclusions.get(scope, []))
    assert (RepositoryType.CODEX_PROJECT in context.repo_types) is (scope == "included")
    tree = context.lint_tree
    assert not forbidden_reads
    assert not context.lint_tree_errors
    block_class = CodexConfigBlock if config else CodexInstructionBlock
    assert bool(tree.find(block_class)) is (scope == "included")
    if scope == "included":
        allow_read = False
        context.exclude_patterns = ["service"]
        context.apply_excludes()
        assert RepositoryType.CODEX_PROJECT not in context.repo_types
        tree = context.lint_tree
        assert not forbidden_reads
        assert not context.lint_tree_errors
        assert not tree.find(block_class)


@pytest.mark.parametrize("lint_external", [False, True])
def test_external_project_config_obeys_authoring_policy(tmp_path, monkeypatch, lint_external):
    root = tmp_path / "repo"
    (root / ".codex").mkdir(parents=True)
    (root / "apm_modules/vendor").mkdir(parents=True)
    (root / "apm.yml").write_text("name: instructions\nversion: 1.0.0\ntargets: []\n")
    (root / "apm_modules/vendor/config.toml").write_text("project_doc_max_bytes = 1\n")
    (root / ".codex/config.toml").symlink_to("../apm_modules/vendor/config.toml")
    (root / "AGENTS.md").write_text("Local instructions")
    original = Path.open

    def scoped_open(path, *args, **kwargs):
        if not lint_external:
            assert path.resolve() != root / "apm_modules/vendor/config.toml", path
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", scoped_open)
    context = RepositoryContext(
        root,
        lint_external_content=lint_external,
        codex_instructions=CodexInstructionOptions(),
    )
    tree = context.lint_tree
    report = tree.find(CodexInstructionsNode)[0].report(tree)
    assert report["complete"] is lint_external
    assert bool(tree.find(CodexConfigBlock)) is lint_external
    assert report["project_doc_max_bytes"] == (1 if lint_external else 32768)
    if not lint_external:
        assert report["charged_bytes"] is None
        assert "configuration is outside" in report["issues"][0]


def test_report_requires_retained_config_evidence(tmp_path):
    context, report = project(
        tmp_path,
        {".codex/config.toml": "project_doc_max_bytes = 1", "AGENTS.md": "local"},
    )
    assert report["complete"]
    tree = context.lint_tree
    block = tree.find(CodexConfigBlock)[0]
    block.parent.children.remove(block)
    tree.invalidate_find_cache()
    report = tree.find(CodexInstructionsNode)[0].report(tree)
    assert not report["complete"]
    assert "configuration is not in the retained lint tree" in report["issues"][0]


def test_project_config_with_inline_roles_remains_retained(tmp_path):
    _, report = project(
        tmp_path,
        {
            ".codex/config.toml": 'project_doc_max_bytes = 100\n[mcp_servers.docs]\nurl = "https://example.com/mcp"\n',
            "AGENTS.md": "Instructions",
        },
    )
    assert report["complete"]
    assert report["config_sources"] == [".codex/config.toml"]


def test_symlink_escape_never_reads_external_instructions_or_config(tmp_path, monkeypatch):
    context, _ = project(tmp_path, {"AGENTS.md": "standard"})
    external = tmp_path / "external"
    external.mkdir()
    (external / "config.toml").write_text("project_doc_max_bytes = 1")
    (external / "secret.md").write_text("external")
    (context.root_path / ".codex").symlink_to(external, target_is_directory=True)
    (context.root_path / "AGENTS.override.md").symlink_to(external / "secret.md")
    original = Path.open

    def contained_open(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(external), f"outside read: {path}"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", contained_open)
    context.rebuild_lint_tree()
    report = context.lint_tree.find(CodexInstructionsNode)[0].report(context.lint_tree)
    assert not report["complete"]
    assert report["project_doc_max_bytes"] == 32768
    assert [e["path"] for e in report["selected"]] == ["AGENTS.override.md"]


def test_in_scope_symlink_charged_per_directory_but_content_checked_once(tmp_path):
    context, _ = project(
        tmp_path, {"AGENTS.md": "root", "child/keep": ""}, cwd="child", project_doc_max_bytes=7
    )
    (context.root_path / "child/AGENTS.md").symlink_to("../AGENTS.md")
    context.rebuild_lint_tree()
    tree = context.lint_tree
    report = tree.find(CodexInstructionsNode)[0].report(tree)
    assert [e["charged_bytes"] for e in report["selected"]] == [4, 3]
    assert len(tree.find(AgentsMdBlock)) == 1


@pytest.mark.parametrize(
    "limit,expected_reads",
    [(0, {}), (3, {"AGENTS.md": 3}), (7, {"AGENTS.md": 4, "child/AGENTS.md": 3})],
)
def test_report_bounds_reads_and_keeps_full_file_sizes(
    tmp_path, monkeypatch, limit, expected_reads
):
    context, _ = project(
        tmp_path,
        {"AGENTS.md": "root", "child/AGENTS.md": "éé"},
        cwd="child",
        project_doc_max_bytes=limit,
    )
    child = context.root_path / "child/AGENTS.md"
    size = 8 * 1024 * 1024
    with child.open("r+b") as stream:
        stream.truncate(size)
    original = Path.open
    reads = {}

    class BoundedRead:
        def __init__(self, path, stream):
            self.name = path.relative_to(context.root_path).as_posix()
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, count=-1):
            assert 0 <= count <= expected_reads[self.name], (self.name, count)
            reads[self.name] = count
            return self.stream.read(count)

    def guarded_open(path, *args, **kwargs):
        assert path.relative_to(context.root_path).as_posix() in expected_reads, path
        return BoundedRead(path, original(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", guarded_open)
    tree = context.lint_tree
    report = tree.find(CodexInstructionsNode)[0].report(tree)
    assert report["complete"]
    assert reads == expected_reads
    assert report["selected_file_bytes"] == size + 4
    assert [entry["file_bytes"] for entry in report["selected"]] == [4, size]
    assert report["charged_bytes"] == limit
    if limit == 7:
        assert report["selected"][1]["truncated"]
        assert report["selected"][1]["text_bytes"] == 5  # Split second é becomes U+FFFD.
        assert report["rendered_project_bytes"] == 11
    else:
        assert report["selected"][1]["status"] == "omitted"


def test_read_failure_marks_rest_of_chain_unknown(tmp_path, monkeypatch):
    context, _ = project(tmp_path, {"AGENTS.md": "root", "child/AGENTS.md": "child"}, cwd="child")
    original = Path.open

    def fail_root(path, *args, **kwargs):
        if path == context.root_path / "AGENTS.md":
            raise PermissionError("permission denied")
        assert path != context.root_path / "child/AGENTS.md", "read after unknown budget"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_root)
    report = context.lint_tree.find(CodexInstructionsNode)[0].report(context.lint_tree)
    assert not report["complete"]
    assert [e["status"] for e in report["selected"]] == ["unknown", "unknown"]


@pytest.mark.parametrize("cwd", ["../outside", "missing", "AGENTS.md"])
def test_cwd_must_be_directory_in_requested_root(tmp_path, cwd):
    context, report = project(tmp_path, {"AGENTS.md": "root"}, cwd=cwd)
    assert not report["complete"]
    assert report["requested_cwd"] == cwd
    assert report["cwd"] is None
    assert repr(cwd) in report["issues"][0]
    assert f"{cwd} (unresolved)" in context.lint_tree.find(CodexInstructionsNode)[0].tree_label()


def test_valid_cwd_preserves_input_and_resolves_symlink(tmp_path):
    root = tmp_path / "repo"
    (root / "service").mkdir(parents=True)
    (root / "alias").symlink_to("service", target_is_directory=True)
    context, report = project(tmp_path, {"service/AGENTS.md": "Package guidance"}, cwd="./alias")
    assert report["complete"]
    assert report["requested_cwd"] == "./alias"
    assert report["cwd"] == str(root / "service")
    assert "[cwd: service]" in context.lint_tree.find(CodexInstructionsNode)[0].tree_label()


def test_config_roundtrip_nulls_and_validation(tmp_path):
    config = LinterConfig.default()
    config.codex_instructions = CodexInstructionOptions("child", 0, ())
    path = tmp_path / ".skillsaw.yaml"
    config.save(path)
    restored = LinterConfig.from_file(path)
    assert restored.codex_instructions == config.codex_instructions
    assert restored.to_dict()["codex-instructions"] == config.codex_instructions.to_dict()
    assert (
        CodexInstructionOptions.from_mapping({"cwd": None, "project_doc_max_bytes": None})
        == CodexInstructionOptions()
    )
    for invalid in [
        [],
        {"cwd": 3},
        {"project_doc_max_bytes": True},
        {"project_doc_max_bytes": -1},
        {"project_doc_max_bytes": 2**63},
        {"project_doc_fallback_filenames": [1]},
        {"typo": 1},
        {1: True},
        {1: True, "typo": True},
    ]:
        with pytest.raises(ValueError):
            CodexInstructionOptions.from_mapping(invalid)


def test_default_lint_and_other_ecosystems_unaffected(tmp_path):
    context, _ = project(
        tmp_path, {"CLAUDE.md": "c" * 20000, "GEMINI.md": "g" * 20000, "QWEN.md": "q" * 20000}
    )
    linter = Linter(context, no_plugins=True)
    assert not any(rule.rule_id == "codex-project-instructions" for rule in linter.rules)
    assert not context.lint_tree.find(CodexInstructionsNode)
    Linter(context, rule_ids={"codex-project-instructions"}, no_plugins=True)
    report = context.lint_tree.find(CodexInstructionsNode)[0].report(context.lint_tree)
    assert report["selected"] == []


@pytest.mark.parametrize(
    "scope", ["included", "excluded", "excluded-target", "external", "escape", "missing"]
)
@pytest.mark.parametrize(
    "filename,block_type,repo_type",
    [
        (".codex/config.toml", CodexConfigBlock, RepositoryType.CODEX_PROJECT),
        (".codex/hooks.json", CodexHooksBlock, RepositoryType.CODEX_PROJECT),
        ("AGENTS.override.md", CodexInstructionBlock, RepositoryType.CODEX_PROJECT),
        ("AGENTS.md", AgentsMdBlock, RepositoryType.AGENTS_MD),
        ("TEAM.md", CodexInstructionBlock, RepositoryType.CODEX_PROJECT),
    ],
)
def test_projected_file_detection_obeys_authoring_scope(
    tmp_path, monkeypatch, scope, filename, block_type, repo_type
):
    root = tmp_path / "repo"
    path = root / "vendor/pkg" / filename
    path.parent.mkdir(parents=True)
    target = path
    if scope in {"external", "excluded-target"}:
        target = root / ("apm_modules/vendor" if scope == "external" else ".private") / "source.txt"
        target.parent.mkdir(parents=True)
        if scope == "external":
            (root / "apm.yml").write_text("name: instructions\nversion: 1.0.0\ntargets: []\n")
        path.symlink_to(target)
    elif scope == "escape":
        target = tmp_path / path.name
        path.symlink_to(target)
    target.write_text(
        "project_doc_max_bytes = 65536\n"
        if path.name == "config.toml"
        else "{}" if path.name == "hooks.json" else "# Package guidance\n\nRun package tests.\n"
    )
    original = Path.open
    allow_read = scope == "included"
    forbidden_reads = []

    def scoped_open(file, *args, **kwargs):
        if not allow_read and file.resolve() == target.resolve():
            forbidden_reads.append(file)
            raise AssertionError(f"out-of-scope read: {file}")
        return original(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", scoped_open)
    context = RepositoryContext(
        root,
        codex_instructions=CodexInstructionOptions(
            cwd="missing" if scope == "missing" else "vendor/pkg",
            project_doc_fallback_filenames=("TEAM.md",),
        ),
        exclude_patterns={"excluded": ["vendor"], "excluded-target": [".private"]}.get(scope, []),
        lint_external_content=False,
    )
    assert (repo_type in context.repo_types) is (scope == "included")
    tree = context.lint_tree
    assert not forbidden_reads
    assert not context.lint_tree_errors
    assert len(tree.find(CodexInstructionsNode)) == 1
    assert bool(tree.find(block_type)) is (scope == "included")
    if scope == "included":
        allow_read = False
        context.exclude_patterns = ["vendor"]
        context.apply_excludes()
        assert repo_type not in context.repo_types
        tree = context.lint_tree
        assert not forbidden_reads
        assert not context.lint_tree_errors
        assert len(tree.find(CodexInstructionsNode)) == 1
        assert not tree.find(block_type)


def test_instruction_projection_refreshes_types_and_auto_rule_activation(tmp_path):
    path = tmp_path / "vendor/pkg/AGENTS.override.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Package guidance\n\nRun package tests.\n")
    context = RepositoryContext(tmp_path)
    config = LinterConfig.default()
    config.rules["codex-project-instructions"] = {"enabled": "auto"}
    config.codex_instructions = CodexInstructionOptions(cwd="vendor/pkg")
    enabled = Linter(context, config, no_plugins=True)
    assert any(rule.rule_id == "codex-project-instructions" for rule in enabled.rules)
    assert RepositoryType.CODEX_PROJECT in context.repo_types
    config.codex_instructions = None
    disabled = Linter(context, config, no_plugins=True)
    assert not any(rule.rule_id == "codex-project-instructions" for rule in disabled.rules)
    assert RepositoryType.CODEX_PROJECT not in context.repo_types
    assert not context.lint_tree.find(CodexInstructionBlock)


@pytest.mark.parametrize("filename", ["config.toml", "hooks.json"])
def test_linter_refreshes_selected_config_types_before_loading_rules(tmp_path, filename):
    path = tmp_path / "vendor/pkg/.codex" / filename
    path.parent.mkdir(parents=True)
    path.write_text("project_doc_max_bytes = 65536\n" if filename == "config.toml" else "{}")
    context = RepositoryContext(tmp_path)
    config = LinterConfig.default()
    config.codex_instructions = CodexInstructionOptions(cwd="vendor/pkg")
    enabled = Linter(context, config, no_plugins=True)
    assert any(rule.rule_id == "codex-hooks-valid" for rule in enabled.rules)
    assert RepositoryType.CODEX_PROJECT in context.repo_types
    block_type = CodexConfigBlock if filename == "config.toml" else CodexHooksBlock
    assert len(context.lint_tree.find(block_type)) == 1
    disabled = Linter(context, no_plugins=True)
    assert not any(rule.rule_id == "codex-hooks-valid" for rule in disabled.rules)
    assert RepositoryType.CODEX_PROJECT not in context.repo_types
    assert not context.lint_tree.find(block_type)


def test_projected_json_hooks_follow_cwd_chain_and_deduplicate_symlinks(tmp_path):
    context, report = project(
        tmp_path,
        {
            "AGENTS.md": "root instructions",
            "vendor/.codex/hooks.json": "{}",
            "vendor/pkg/.codex/hooks.json": "{}",
            "vendor/sibling/.codex/hooks.json": "{}",
            "vendor/pkg/deeper/.codex/hooks.json": "{}",
        },
        cwd="vendor/pkg",
    )
    paths = [block.path for block in context.lint_tree.find(CodexHooksBlock)]
    assert paths == [
        context.root_path / "vendor/.codex/hooks.json",
        context.root_path / "vendor/pkg/.codex/hooks.json",
    ]
    assert report["complete"]
    assert [source["path"] for source in report["selected"]] == ["AGENTS.md"]
    child = paths[1]
    child.unlink()
    child.symlink_to(paths[0])
    context.rebuild_lint_tree()
    assert len(context.lint_tree.find(CodexHooksBlock)) == 1


def test_excluded_json_hooks_do_not_make_instruction_budget_incomplete(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    hooks = root / "vendor/pkg/.codex/hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text("{}")
    (root / "AGENTS.md").write_text("Local instructions")
    original = Path.open

    def scoped_open(path, *args, **kwargs):
        assert path != hooks, "excluded hooks read"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", scoped_open)
    context = RepositoryContext(
        root,
        codex_instructions=CodexInstructionOptions(cwd="vendor/pkg"),
        exclude_patterns=["vendor/pkg/.codex/hooks.json"],
    )
    tree = context.lint_tree
    report = tree.find(CodexInstructionsNode)[0].report(tree)
    assert report["complete"]
    assert report["charged_bytes"] == len("Local instructions")
    assert not tree.find(CodexHooksBlock)


def test_override_only_repository_gets_content_coverage(tmp_path):
    context, _ = project(tmp_path, {"a/AGENTS.override.md": "Override instructions"})
    assert RepositoryType.CODEX_PROJECT in context.repo_types
    assert len(context.lint_tree.find(CodexInstructionBlock)) == 1
    assert not context.lint_tree.find(AgentsMdBlock)


def test_severity_override(tmp_path):
    context, _ = project(tmp_path, {"AGENTS.md": "text"})
    config = LinterConfig.default()
    config.codex_instructions = CodexInstructionOptions(project_doc_max_bytes=1)
    config.rules["codex-project-instructions"] = {"enabled": True, "severity": "info"}
    linter = Linter(
        context, config=config, rule_ids={"codex-project-instructions"}, no_plugins=True
    )
    rule = next(rule for rule in linter.rules if rule.rule_id == "codex-project-instructions")
    assert rule.check(context)[0].severity == Severity.INFO


def test_global_config_not_read(tmp_path, monkeypatch):
    secret_home = tmp_path / "home"
    secret_home.mkdir()
    (secret_home / "config.toml").write_text("project_doc_max_bytes = 1")
    (secret_home / "AGENTS.md").write_text("Global standard instructions")
    (secret_home / "AGENTS.override.md").write_text("Global override instructions")
    monkeypatch.setenv("CODEX_HOME", str(secret_home))
    original = Path.open

    def local_open(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(secret_home), f"global read: {path}"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", local_open)
    _, report = project(tmp_path, {"AGENTS.md": "root"})
    assert report["project_doc_max_bytes"] == 32768
    assert "assumed" in report["limit_source"]


@pytest.mark.parametrize(
    "args", [["--cwd", "."], ["--format", "json"], ["--codex-instructions", "--format", "dot"]]
)
def test_invalid_tree_flag_combinations(tmp_path, args):
    result = run_cli(["tree", str(tmp_path), *args])
    assert result.returncode == 2


def test_cli_projection_no_files(tmp_path):
    result = run_cli(["tree", str(tmp_path), "--codex-instructions", "--format", "json"])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["selected"] == []


def test_text_inspection_preserves_lines_and_all_assumptions(tmp_path):
    project(tmp_path, {"AGENTS.md": "root"})
    result = run_cli(["tree", str(tmp_path / "repo"), "--codex-instructions"])
    assert result.returncode == 0
    assert len(result.stdout.splitlines()) > 10
    assert "Global/user/thread instructions" in result.stdout
    assert "AGENTS.md: loaded" in result.stdout
