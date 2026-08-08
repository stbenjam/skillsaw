"""
Tests for the lint tree data structure and tree builder.
"""

import json
from pathlib import Path

from skillsaw.blocks import (
    BodyContent,
    ClineWorkflowBlock,
    CopilotAgentBlock,
    CopilotPromptBlock,
    CursorCommandBlock,
    CursorPromptHookBlock,
    CursorRuleBlock,
    InstructionBlock,
    QwenMdBlock,
    VsCodeMcpBlock,
)
from skillsaw.config import LinterConfig
from skillsaw.lint_target import (
    LintTarget,
    ApmConfigNode,
    ApmNode,
    CodeRabbitNode,
    CodexMarketplaceConfigNode,
    CodexPluginNode,
    MarketplaceConfigNode,
    MarketplaceNode,
    PluginNode,
    SkillNode,
)
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter

# --- LintTarget.walk() ---


def test_walk_single_node():
    root = LintTarget(path=Path("/root"))
    nodes = list(root.walk())
    assert len(nodes) == 1
    assert nodes[0] is root


def test_walk_flat_children():
    root = LintTarget(path=Path("/root"))
    a = LintTarget(path=Path("/a"))
    b = LintTarget(path=Path("/b"))
    root.children = [a, b]

    nodes = list(root.walk())
    assert len(nodes) == 3
    assert nodes[0] is root
    assert nodes[1] is a
    assert nodes[2] is b


def test_walk_nested():
    root = LintTarget(path=Path("/root"))
    plugin = PluginNode(path=Path("/plugin"))
    skill = SkillNode(path=Path("/skill"))
    plugin.children = [skill]
    root.children = [plugin]

    nodes = list(root.walk())
    assert len(nodes) == 3
    assert nodes[0] is root
    assert nodes[1] is plugin
    assert nodes[2] is skill


# --- LintTarget.find() ---


def test_find_by_type():
    root = LintTarget(path=Path("/root"))
    p1 = PluginNode(path=Path("/p1"))
    p2 = PluginNode(path=Path("/p2"))
    s1 = SkillNode(path=Path("/s1"))
    p1.children = [s1]
    root.children = [p1, p2]

    plugins = root.find(PluginNode)
    assert len(plugins) == 2
    assert all(isinstance(p, PluginNode) for p in plugins)

    skills = root.find(SkillNode)
    assert len(skills) == 1
    assert skills[0] is s1


def test_find_returns_empty_when_no_match():
    root = LintTarget(path=Path("/root"))
    root.children = [PluginNode(path=Path("/p"))]
    assert root.find(SkillNode) == []


def test_find_polymorphic():
    """find(LintTarget) returns all nodes regardless of subtype."""
    root = LintTarget(path=Path("/root"))
    root.children = [PluginNode(path=Path("/p")), SkillNode(path=Path("/s"))]
    assert len(root.find(LintTarget)) == 3


# --- LintTarget.find_parent() ---


def test_find_parent_returns_nearest():
    root = LintTarget(path=Path("/root"))
    marketplace = MarketplaceNode(path=Path("/plugins"))
    plugin = PluginNode(path=Path("/plugin"))
    skill = SkillNode(path=Path("/skill"))
    leaf = LintTarget(path=Path("/leaf"))

    skill.children = [leaf]
    plugin.children = [skill]
    marketplace.children = [plugin]
    root.children = [marketplace]
    root.set_parents()

    parent = root.find_parent(leaf, PluginNode)
    assert parent is plugin

    parent = root.find_parent(skill, PluginNode)
    assert parent is plugin


def test_find_parent_returns_none_when_no_match():
    root = LintTarget(path=Path("/root"))
    child = LintTarget(path=Path("/child"))
    root.children = [child]
    root.set_parents()

    assert root.find_parent(child, PluginNode) is None


def test_find_parent_skips_non_ancestors():
    root = LintTarget(path=Path("/root"))
    p1 = PluginNode(path=Path("/p1"))
    p2 = PluginNode(path=Path("/p2"))
    target = LintTarget(path=Path("/target"))
    p2.children = [target]
    root.children = [p1, p2]
    root.set_parents()

    parent = root.find_parent(target, PluginNode)
    assert parent is p2


# --- Tree labels ---


def test_tree_labels():
    assert LintTarget(path=Path("/foo")).tree_label() == "foo"
    assert MarketplaceConfigNode(path=Path("/m.json")).tree_label() == "marketplace.json"
    assert MarketplaceNode(path=Path("/plugins")).tree_label() == "plugins/ [marketplace]"
    assert PluginNode(path=Path("/my-plugin")).tree_label() == "my-plugin/ [plugin]"
    assert CodexPluginNode(path=Path("/my-plugin")).tree_label() == "my-plugin/ [codex plugin]"
    assert (
        CodexMarketplaceConfigNode(path=Path("/api_marketplace.json")).tree_label()
        == "api_marketplace.json [codex]"
    )
    assert SkillNode(path=Path("/my-skill")).tree_label() == "my-skill/ [skill]"
    assert ApmConfigNode(path=Path("/apm.yml")).tree_label() == "apm.yml"
    assert ApmNode(path=Path("/.apm")).tree_label() == ".apm/"
    assert CodeRabbitNode(path=Path("/.coderabbit.yaml")).tree_label() == ".coderabbit.yaml"


# --- print_tree ---


def test_print_tree_nested():
    root = LintTarget(path=Path("/repo"))
    plugin = PluginNode(path=Path("/repo/my-plugin"))
    skill = SkillNode(path=Path("/repo/my-plugin/my-skill"))
    plugin.children = [skill]
    root.children = [plugin]

    output = root.print_tree(root_path=Path("/repo"))
    assert "repo/" in output
    assert "my-plugin/ [plugin]" in output
    assert "my-skill/ [skill]" in output


# --- Tree builder integration ---


def test_tree_contains_typed_nodes(temp_dir):
    """A marketplace repo should produce typed tree nodes."""
    claude_plugin = temp_dir / ".claude-plugin"
    claude_plugin.mkdir()
    (claude_plugin / "marketplace.json").write_text('{"name": "test", "plugins": []}')

    plugins_dir = temp_dir / "plugins"
    plugins_dir.mkdir()
    plugin = plugins_dir / "my-plugin"
    plugin.mkdir()
    (plugin / "plugin.json").write_text('{"name": "my-plugin"}')
    commands = plugin / "commands"
    commands.mkdir()
    (commands / "hello.md").write_text("## Description\nHello\n## Usage\n/hello\n")
    skill_dir = plugin / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: Test\n---\n")

    context = RepositoryContext(temp_dir)
    tree = context.lint_tree

    assert len(tree.find(MarketplaceConfigNode)) == 1
    assert len(tree.find(MarketplaceNode)) == 1
    assert len(tree.find(PluginNode)) == 1
    assert len(tree.find(SkillNode)) == 1


def test_tree_contains_apm_nodes(temp_dir):
    """An APM repo should produce ApmConfigNode and ApmNode."""
    (temp_dir / "apm.yml").write_text("name: test\nversion: 1.0.0\ndescription: Test\n")
    apm_dir = temp_dir / ".apm"
    apm_dir.mkdir()
    instructions = apm_dir / "instructions"
    instructions.mkdir()
    (instructions / "coding.instructions.md").write_text("# Coding\nBe good.\n")

    context = RepositoryContext(temp_dir)
    tree = context.lint_tree

    assert len(tree.find(ApmConfigNode)) == 1
    assert tree.find(ApmConfigNode)[0].path.name == "apm.yml"
    assert len(tree.find(ApmNode)) == 1


def test_tree_contains_coderabbit_node(temp_dir):
    """A repo with .coderabbit.yaml should produce a CodeRabbitNode."""
    (temp_dir / ".coderabbit.yaml").write_text("reviews:\n  instructions: Be thorough\n")

    context = RepositoryContext(temp_dir)
    tree = context.lint_tree

    assert len(tree.find(CodeRabbitNode)) == 1


def test_tree_contains_editor_tool_blocks(temp_dir):
    """Cursor, Copilot and Cline content files each get their own block type."""
    (temp_dir / ".cursor" / "rules" / "backend").mkdir(parents=True)
    (temp_dir / ".cursor" / "rules" / "backend" / "api.mdc").write_text(
        "---\ndescription: API rules\n---\n\nReturn Pydantic models.\n"
    )
    (temp_dir / ".cursor" / "commands").mkdir()
    (temp_dir / ".cursor" / "commands" / "review.md").write_text("# Review\n\nRead the diff.\n")
    (temp_dir / ".github" / "prompts").mkdir(parents=True)
    (temp_dir / ".github" / "prompts" / "log.prompt.md").write_text(
        "---\ndescription: Draft a changelog\n---\n\nGroup the merged pull requests.\n"
    )
    (temp_dir / ".github" / "agents").mkdir()
    (temp_dir / ".github" / "agents" / "sec.agent.md").write_text(
        "---\ndescription: Security reviewer\n---\n\nReport auth defects.\n"
    )
    (temp_dir / ".github" / "chatmodes").mkdir()
    (temp_dir / ".github" / "chatmodes" / "plan.chatmode.md").write_text(
        "---\ndescription: Planner\n---\n\nProduce a plan.\n"
    )
    (temp_dir / ".clinerules" / "workflows").mkdir(parents=True)
    (temp_dir / ".clinerules" / "style.md").write_text("# Style\n\nPrefer small commits.\n")
    (temp_dir / ".clinerules" / "policy.txt").write_text("Never force push to main.\n")
    (temp_dir / ".clinerules" / "workflows" / "release.md").write_text("# Release\n\nTag it.\n")

    tree = RepositoryContext(temp_dir).lint_tree

    def names(block_cls):
        return {b.path.name for b in tree.find(block_cls)}

    # Nested rule directories are ordinary rule files, not decoration.
    assert names(CursorRuleBlock) == {"api.mdc"}
    assert names(CursorCommandBlock) == {"review.md"}
    assert names(CopilotPromptBlock) == {"log.prompt.md"}
    assert names(CopilotAgentBlock) == {"sec.agent.md", "plan.chatmode.md"}
    # Workflows are claimed before the always-on sweep, so they are budgeted
    # as on-demand commands rather than as system-prompt instructions.
    assert names(ClineWorkflowBlock) == {"release.md"}
    # Exact, not a subset: if the dedup regressed, release.md would land in
    # both sets and be double-budgeted as always-on system-prompt text.
    assert names(InstructionBlock) == {"style.md", "policy.txt"}


def test_setext_underline_is_not_read_as_mdc_frontmatter(temp_dir):
    """``----`` opens a heading rule, so the prose under it stays body text.

    Treating it as a frontmatter delimiter would end the block at the next
    thematic break and hand the content rules a body missing everything
    before it.
    """
    rules = temp_dir / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "notes.mdc").write_text(
        "----\n\nUse int64 minor units for money.\n\n---\n\nMore prose.\n"
    )

    tree = RepositoryContext(temp_dir).lint_tree
    block = tree.find(CursorRuleBlock)[0]
    body = "".join(
        child.read_body(strip_code_blocks=False) or "" for child in block.find(BodyContent)
    )

    assert "int64 minor units" in body
    assert "More prose." in body


def test_cursor_prompt_hook_text_is_a_content_block(temp_dir):
    """The prompt is prose the agent reads; hooks.json around it stays config."""
    cursor = temp_dir / ".cursor"
    cursor.mkdir(parents=True)
    (cursor / "hooks.json").write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "beforeShellExecution": [
                        {"type": "prompt", "prompt": "Check the ledger first."},
                        {"command": "./audit.sh"},
                    ]
                },
            }
        )
    )

    tree = RepositoryContext(temp_dir).lint_tree
    prompts = tree.find(CursorPromptHookBlock)

    assert [b.json_path for b in prompts] == ["hooks.beforeShellExecution[0].prompt"]
    assert prompts[0].read_body(strip_code_blocks=False) == "Check the ledger first."
    # JSON has no line numbers, so every body line maps to file-level.
    assert prompts[0].file_line(1) == 0
    # The command hook is not prose and must not become one.
    assert len(prompts) == 1


def test_a_copilot_agent_named_instructions_md_stays_an_agent(temp_dir):
    """The repo-wide *.instructions.md sweep must not outrank a Copilot directory.

    VS Code reads any .md under .github/agents as a custom agent. The sweep
    runs first and claims paths globally, so without a carve-out the file
    would attach as an InstructionBlock — frontmatter linted as prose, and
    the instruction budget instead of the agent one.
    """
    agents = temp_dir / ".github" / "agents"
    agents.mkdir(parents=True)
    (agents / "reviewer.instructions.md").write_text(
        "---\ndescription: Security reviewer\n---\n\nCheck all inputs.\n"
    )

    tree = RepositoryContext(temp_dir).lint_tree

    assert [b.path.name for b in tree.find(CopilotAgentBlock)] == ["reviewer.instructions.md"]
    assert tree.find(InstructionBlock) == []


def test_apm_compiled_copilot_output_is_not_linted(temp_dir):
    """APM writes .github/agents from .apm/agents; linting both reports twice."""
    (temp_dir / ".apm" / "agents").mkdir(parents=True)
    (temp_dir / ".apm" / "agents" / "sec.agent.md").write_text(
        "---\ndescription: Security reviewer\n---\n\nCheck the inputs.\n"
    )
    (temp_dir / ".github" / "agents").mkdir(parents=True)
    (temp_dir / ".github" / "agents" / "sec.agent.md").write_text(
        "---\ndescription: Security reviewer\n---\n\nCheck the inputs.\n"
    )
    # Authored .github content with no .apm source keeps being linted.
    (temp_dir / ".github" / "prompts").mkdir()
    (temp_dir / ".github" / "prompts" / "log.prompt.md").write_text(
        "---\ndescription: Log review\n---\n\nSummarise the log.\n"
    )

    tree = RepositoryContext(temp_dir).lint_tree

    assert tree.find(CopilotAgentBlock) == []
    assert [b.path.name for b in tree.find(CopilotPromptBlock)] == ["log.prompt.md"]


def test_tree_finds_editor_tool_dirs_in_subpackages(temp_dir):
    """Cursor reads the nearest .cursor directory, so a monorepo package keeps its own."""
    nested = temp_dir / "apps" / "web" / ".cursor" / "rules"
    nested.mkdir(parents=True)
    (nested / "web.mdc").write_text("---\ndescription: Web rules\n---\n\nUse Tailwind.\n")

    tree = RepositoryContext(temp_dir).lint_tree

    assert [b.path.name for b in tree.find(CursorRuleBlock)] == ["web.mdc"]


def test_tree_reads_vscode_mcp_servers_key(temp_dir):
    """VS Code spells the server map ``servers`` and adds a non-server ``inputs``."""
    (temp_dir / ".vscode").mkdir()
    (temp_dir / ".vscode" / "mcp.json").write_text(
        '{"inputs": [{"id": "tok", "type": "promptString"}], '
        '"servers": {"fetch": {"type": "http", "url": "https://example.com/mcp"}}}'
    )

    tree = RepositoryContext(temp_dir).lint_tree

    blocks = tree.find(VsCodeMcpBlock)
    assert len(blocks) == 1
    assert blocks[0].server_names == {"fetch"}


def test_tree_contains_qwen_md_block(temp_dir):
    """QWEN.md is an instruction file in its own right, like GEMINI.md."""
    (temp_dir / "QWEN.md").write_text("# Qwen\n\nActivate the virtualenv first.\n")

    tree = RepositoryContext(temp_dir).lint_tree

    blocks = tree.find(QwenMdBlock)
    assert len(blocks) == 1
    assert blocks[0].category == "qwen-md"


def test_tree_rejects_instruction_symlink_outside_repo(tmp_path):
    """Generic block discovery must not attach a symlinked external file."""
    outside = tmp_path / "outside.md"
    outside.write_text("external instructions\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = repo / ".cursorrules"
    linked.symlink_to(outside)

    tree = RepositoryContext(repo).lint_tree

    assert all(node.path != linked for node in tree.walk())


def test_tree_rejects_coderabbit_symlink_outside_repo(tmp_path):
    """CodeRabbit discovery must not parse a symlinked external config."""
    outside = tmp_path / "outside.yaml"
    outside.write_text("reviews:\n  instructions: external\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".coderabbit.yaml").symlink_to(outside)

    tree = RepositoryContext(repo).lint_tree

    assert tree.find(CodeRabbitNode) == []


def test_unresolvable_repository_root_surfaces_lint_error(temp_dir, monkeypatch):
    """A failed canonical-root lookup must not silently produce a partial tree."""
    context = RepositoryContext(temp_dir)
    monkeypatch.setattr("skillsaw.lint_tree.safe_resolve", lambda path: None)

    linter = Linter(context, LinterConfig.default())
    first_errors = [v for v in linter.run() if v.rule_id == "repository-path-error"]
    second_errors = [v for v in linter.run() if v.rule_id == "repository-path-error"]

    assert len(first_errors) == 1
    assert len(second_errors) == 1
    assert str(temp_dir) in first_errors[0].message
    assert list(context.lint_tree.walk()) == [context.lint_tree]


def test_content_blocks_returns_all_content(temp_dir):
    """content_blocks() should return all ContentBlock subclasses polymorphically."""
    (temp_dir / "CLAUDE.md").write_text("# Instructions\nBe helpful.\n")

    context = RepositoryContext(temp_dir)
    blocks = context.lint_tree.content_blocks()

    assert len(blocks) >= 1
    assert all(hasattr(b, "category") for b in blocks)


def test_content_blocks_excludes_mcp_blocks(temp_dir):
    """content_blocks() must not include McpBlock instances (regression)."""
    import json
    from skillsaw.rules.builtin.content_analysis import McpBlock

    plugin_dir = temp_dir / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps({"name": "test"}))
    (temp_dir / "CLAUDE.md").write_text("# Instructions\nBe helpful.\n")
    (temp_dir / ".mcp.json").write_text(json.dumps({"mcpServers": {"s": {"command": "x"}}}))

    context = RepositoryContext(temp_dir)
    blocks = context.lint_tree.content_blocks()

    assert len(blocks) >= 1
    assert not any(isinstance(b, McpBlock) for b in blocks)


def test_estimate_tokens_content_block(temp_dir):
    """ContentBlock.estimate_tokens() returns len(body) // 4."""
    from skillsaw.rules.builtin.content_analysis import FileContentBlock, InstructionBlock

    f = temp_dir / "test.md"
    f.write_text("a" * 400)
    block = InstructionBlock(path=f)
    assert block.estimate_tokens() == 100


def test_estimate_tokens_container_sums_children(temp_dir):
    """Container nodes sum their children's tokens."""
    from skillsaw.rules.builtin.content_analysis import InstructionBlock

    f1 = temp_dir / "a.md"
    f1.write_text("x" * 200)
    f2 = temp_dir / "b.md"
    f2.write_text("y" * 400)

    root = LintTarget(path=temp_dir)
    root.children = [InstructionBlock(path=f1), InstructionBlock(path=f2)]
    assert root.estimate_tokens() == 150  # 50 + 100


def test_print_tree_shows_tokens(temp_dir):
    """print_tree() output includes token counts."""
    from skillsaw.rules.builtin.content_analysis import InstructionBlock

    f = temp_dir / "CLAUDE.md"
    f.write_text("x" * 80)

    root = LintTarget(path=temp_dir)
    root.children = [InstructionBlock(path=f)]
    output = root.print_tree(root_path=temp_dir)
    assert "tokens)" in output
    assert "(20 tokens)" in output


def test_print_dot_structure(temp_dir):
    """print_dot() produces valid DOT with nodes and edges."""
    from skillsaw.rules.builtin.content_analysis import InstructionBlock

    f = temp_dir / "CLAUDE.md"
    f.write_text("hello world")

    root = LintTarget(path=temp_dir)
    root.children = [InstructionBlock(path=f)]
    dot = root.print_dot(root_path=temp_dir)

    assert dot.startswith("digraph lint_tree {")
    assert dot.strip().endswith("}")
    assert "n0" in dot
    assert "n1" in dot
    assert "n0 -> n1" in dot
    assert "tokens)" in dot
    assert "fillcolor=" in dot


def test_tree_all_rules_use_tree(temp_dir):
    """Verify no rule uses context.plugins or context.skills directly."""
    import ast
    from pathlib import Path

    rules_dir = Path("src/skillsaw/rules/builtin")
    for py_file in sorted(rules_dir.glob("*.py")):
        if py_file.name in ("__init__.py", "utils.py", "content_analysis.py"):
            continue
        source = py_file.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for method in ast.walk(node):
                    if isinstance(method, ast.FunctionDef) and method.name == "check":
                        method_src = ast.get_source_segment(source, method)
                        if method_src:
                            assert "context.plugins" not in method_src, (
                                f"{py_file.name}:{node.name}.check() "
                                f"uses context.plugins instead of tree"
                            )
                            assert "context.skills" not in method_src, (
                                f"{py_file.name}:{node.name}.check() "
                                f"uses context.skills instead of tree"
                            )


def test_all_lint_targets_are_hashable():
    """Every LintTarget subclass must be hashable (usable as a dict key).

    Violations are grouped by block via dict.setdefault(block, []).
    If a LintTarget subclass is decorated with bare @dataclass (without
    eq=False), Python generates __eq__ and sets __hash__ = None, making
    it unhashable. Regression guard for GH-245.
    """
    # Force-import all modules that define LintTarget subclasses
    import importlib

    for mod in [
        "skillsaw.lint_target",
        "skillsaw.rules.builtin.content_analysis",
    ]:
        importlib.import_module(mod)

    def _all_subclasses(cls):
        result = set()
        for sub in cls.__subclasses__():
            result.add(sub)
            result.update(_all_subclasses(sub))
        return result

    for cls in _all_subclasses(LintTarget):
        assert cls.__hash__ is not None, (
            f"{cls.__qualname__} is not hashable — "
            f"add @dataclass(eq=False) and define __eq__/__hash__"
        )
