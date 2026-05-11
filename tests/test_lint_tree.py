"""
Tests for the lint tree data structure and tree builder.
"""

from pathlib import Path

from skillsaw.lint_target import (
    LintTarget,
    ApmConfigNode,
    ApmNode,
    CodeRabbitNode,
    MarketplaceConfigNode,
    MarketplaceNode,
    PluginNode,
    SkillNode,
)
from skillsaw.context import RepositoryContext

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

    parent = root.find_parent(leaf, PluginNode)
    assert parent is plugin

    parent = root.find_parent(skill, PluginNode)
    assert parent is plugin


def test_find_parent_returns_none_when_no_match():
    root = LintTarget(path=Path("/root"))
    child = LintTarget(path=Path("/child"))
    root.children = [child]

    assert root.find_parent(child, PluginNode) is None


def test_find_parent_skips_non_ancestors():
    root = LintTarget(path=Path("/root"))
    p1 = PluginNode(path=Path("/p1"))
    p2 = PluginNode(path=Path("/p2"))
    target = LintTarget(path=Path("/target"))
    p2.children = [target]
    root.children = [p1, p2]

    parent = root.find_parent(target, PluginNode)
    assert parent is p2


# --- Tree labels ---


def test_tree_labels():
    assert LintTarget(path=Path("/foo")).tree_label() == "foo"
    assert MarketplaceConfigNode(path=Path("/m.json")).tree_label() == "marketplace.json"
    assert MarketplaceNode(path=Path("/plugins")).tree_label() == "plugins/ [marketplace]"
    assert PluginNode(path=Path("/my-plugin")).tree_label() == "my-plugin/ [plugin]"
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


def test_content_blocks_returns_all_content(temp_dir):
    """content_blocks() should return all ContentBlock subclasses polymorphically."""
    (temp_dir / "CLAUDE.md").write_text("# Instructions\nBe helpful.\n")

    context = RepositoryContext(temp_dir)
    blocks = context.lint_tree.content_blocks()

    assert len(blocks) >= 1
    assert all(hasattr(b, "category") for b in blocks)


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
