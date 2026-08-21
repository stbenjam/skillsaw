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
from skillsaw.rules.builtin.cursor import CursorRulesValidRule

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


def test_editor_dirs_claim_instructions_md_only_where_their_glob_matches(temp_dir):
    """Ownership and the sweep read one table, so no file falls between them.

    Standing aside where the owner's glob does not match would drop the file
    from the tree entirely — worse than the misclassification it prevents.
    """
    for rel, text in {
        ".cursor/commands/review.instructions.md": "---\ndescription: Review\n---\n\nGo.\n",
        ".clinerules/workflows/release.instructions.md": "# Release\n\nTag it.\n",
        # Three levels deep: depth must not decide ownership.
        ".github/agents/team/backend/rev.instructions.md": (
            "---\ndescription: Backend\n---\n\nCheck handlers.\n"
        ),
        # These globs take *.prompt.md / *.chatmode.md, so the sweep keeps them.
        ".github/prompts/notes.instructions.md": "# Notes\n\nProse.\n",
        ".github/chatmodes/modes.instructions.md": "# Modes\n\nProse.\n",
        # .github/instructions is the sweep's own home.
        ".github/instructions/style.instructions.md": "# Style\n\nProse.\n",
    }.items():
        target = temp_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    tree = RepositoryContext(temp_dir).lint_tree

    assert [b.path.name for b in tree.find(CursorCommandBlock)] == ["review.instructions.md"]
    assert [b.path.name for b in tree.find(ClineWorkflowBlock)] == ["release.instructions.md"]
    assert [b.path.name for b in tree.find(CopilotAgentBlock)] == ["rev.instructions.md"]
    # Nothing dropped: the three the editor globs decline stay instructions.
    assert sorted(b.path.name for b in tree.find(InstructionBlock)) == [
        "modes.instructions.md",
        "notes.instructions.md",
        "style.instructions.md",
    ]


def test_only_top_level_cline_dirs_are_reserved(temp_dir):
    """Cline reserves workflows/hooks/skills at the top of .clinerules, not below.

    A rule filed under ``backend/hooks/`` is ordinary prose Cline does
    concatenate; matching the name at any depth dropped it from the tree.
    """
    (temp_dir / ".clinerules" / "backend" / "hooks").mkdir(parents=True)
    (temp_dir / ".clinerules" / "backend" / "hooks" / "policy.md").write_text(
        "# Policy\n\nNever bypass the ledger check.\n"
    )
    (temp_dir / ".clinerules" / "hooks").mkdir()
    (temp_dir / ".clinerules" / "hooks" / "pre.md").write_text("# Real hook dir\n\nSkip me.\n")

    tree = RepositoryContext(temp_dir).lint_tree

    assert [b.path.name for b in tree.find(InstructionBlock)] == ["policy.md"]


def test_apm_without_a_copilot_target_keeps_authored_github_content(temp_dir):
    """A source directory alone does not make the .github copy generated."""
    (temp_dir / "apm.yml").write_text(
        "name: t\nversion: 1.0.0\ndescription: Test\ntargets:\n  - claude\n"
    )
    (temp_dir / ".apm" / "agents").mkdir(parents=True)
    (temp_dir / ".apm" / "agents" / "src.agent.md").write_text(
        "---\ndescription: APM source\n---\n\nAuthored in .apm.\n"
    )
    (temp_dir / ".github" / "agents").mkdir(parents=True)
    (temp_dir / ".github" / "agents" / "custom.agent.md").write_text(
        "---\ndescription: Hand-written\n---\n\nAPM never generated this.\n"
    )

    tree = RepositoryContext(temp_dir).lint_tree

    assert [b.path.name for b in tree.find(CopilotAgentBlock)] == ["custom.agent.md"]


def test_apm_compiled_copilot_output_is_content_suppressed(temp_dir):
    """APM writes .github/agents from .apm/agents; the compiled copy is content-suppressed.

    Linting it as authored prose would double every finding it shares with
    its `.apm/` source, so content and dedup findings are filtered out — but
    the block stays in the tree with ``content_suppressed`` set so the
    security rules still scan it. Authored `.github` content with no `.apm/`
    source behind it keeps being linted normally.
    """
    (temp_dir / "apm.yml").write_text(
        "name: t\nversion: 1.0.0\ndescription: Test\ntargets:\n  - copilot\n"
    )
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

    compiled = tree.find(CopilotAgentBlock)
    assert [b.path.name for b in compiled] == ["sec.agent.md"]
    assert all(b.content_suppressed for b in compiled)
    # The authored prompt has no .apm source, so it is not suppressed.
    prompts = tree.find(CopilotPromptBlock)
    assert [b.path.name for b in prompts] == ["log.prompt.md"]
    assert not any(b.content_suppressed for b in prompts)


def test_vendored_instruction_file_keeps_attaching(temp_dir):
    """Yielding to an editor loop that never runs drops the file entirely.

    Discovery keeps a vendored ``.github`` out of ``agent_tool_dirs`` while
    the repository-wide sweep still collects instruction files from it. A
    claim test that matched on the directory *name* alone therefore stood
    aside for an owner that never arrived, and the file left the tree —
    invisible to every content and security rule.
    """
    body = "---\ndescription: Security reviewer\n---\n\nCheck every input.\n"
    vendored = temp_dir / "vendor" / "pkg" / ".github" / "agents"
    vendored.mkdir(parents=True)
    (vendored / "reviewer.instructions.md").write_text(body)
    owned = temp_dir / ".github" / "agents"
    owned.mkdir(parents=True)
    (owned / "reviewer.instructions.md").write_text(body)

    tree = RepositoryContext(temp_dir).lint_tree

    # The vendored copy has no editor owner, so the sweep keeps it as prose.
    instruction_paths = {b.path for b in tree.find(InstructionBlock)}
    assert vendored / "reviewer.instructions.md" in instruction_paths
    # The owned copy still goes to its specific owner rather than the sweep.
    assert [b.path for b in tree.find(CopilotAgentBlock)] == [owned / "reviewer.instructions.md"]
    assert owned / "reviewer.instructions.md" not in instruction_paths


def test_excluded_editor_dir_leaves_its_instruction_file_to_the_sweep(temp_dir):
    """An excluded `.github` is not walked either, so the sweep must keep the file."""
    nested = temp_dir / "packages" / ".github" / "agents"
    nested.mkdir(parents=True)
    (nested / "reviewer.instructions.md").write_text(
        "---\ndescription: Security reviewer\n---\n\nCheck every input.\n"
    )

    tree = RepositoryContext(temp_dir, exclude_patterns=["packages/*"]).lint_tree

    # Excluded means excluded — but it must be the exclusion that drops it,
    # not a claim handed to a loop that skips it for a different reason.
    assert tree.find(CopilotAgentBlock) == []
    assert [b.path for b in tree.find(InstructionBlock)] == []


def test_prose_about_generated_files_does_not_drop_an_authored_copilot_file(temp_dir):
    """The stamp is a banner, not a phrase the document happens to contain.

    Matching anywhere meant an authored Copilot file reading "review code
    generated by APM CLI before merging" was classified as output and left
    the tree — invisible to every content, security and budget rule.
    """
    (temp_dir / "apm.yml").write_text(
        "name: t\nversion: 1.0.0\ndescription: Test\ntargets:\n  - copilot\n"
    )
    (temp_dir / ".apm" / "instructions").mkdir(parents=True)
    (temp_dir / ".apm" / "instructions" / "dev.instructions.md").write_text(
        "---\ndescription: Dev rules\n---\n\nRun the tests before pushing.\n"
    )
    (temp_dir / ".github").mkdir()
    (temp_dir / ".github" / "copilot-instructions.md").write_text(
        "# Copilot guidance\n\n" "Review code generated by APM CLI before merging it into main.\n"
    )

    names = {b.path.name for b in RepositoryContext(temp_dir).lint_tree.find(InstructionBlock)}

    assert "copilot-instructions.md" in names


def test_apm_leaves_a_cursor_dir_alone_when_it_targets_only_claude(temp_dir):
    """APM writes `.cursor/` only when `cursor` is a target.

    Suppressing it regardless hid a hand-authored Cursor tree from every
    rule the branch adds — the same mistake the `.github` guard avoids.
    """
    (temp_dir / "apm.yml").write_text(
        "name: t\nversion: 1.0.0\ndescription: Test\ntargets:\n  - claude\n"
    )
    (temp_dir / ".apm" / "instructions").mkdir(parents=True)
    (temp_dir / ".cursor" / "rules").mkdir(parents=True)
    (temp_dir / ".cursor" / "rules" / "hand.mdc").write_text(
        "---\ndescription: Hand written\n---\n\nUse the shared client.\n"
    )

    tree = RepositoryContext(temp_dir).lint_tree

    assert [b.path.name for b in tree.find(CursorRuleBlock)] == ["hand.mdc"]


def test_an_explicitly_empty_targets_list_suppresses_nothing(temp_dir):
    """`targets: []` parsed fine and means "compile nothing" — it is not the
    unreadable-manifest fallback, so no editor directory is APM output."""
    (temp_dir / "apm.yml").write_text("name: t\nversion: 1.0.0\ntargets: []\n")
    (temp_dir / ".apm" / "instructions").mkdir(parents=True)
    (temp_dir / ".cursor" / "rules").mkdir(parents=True)
    (temp_dir / ".cursor" / "rules" / "hand.mdc").write_text(
        "---\ndescription: Hand written\n---\n\nUse the client.\n"
    )

    tree = RepositoryContext(temp_dir).lint_tree

    assert [b.path.name for b in tree.find(CursorRuleBlock)] == ["hand.mdc"]


def test_apm_content_suppresses_a_cursor_dir_it_compiles(temp_dir):
    """A `.cursor/` dir APM compiles attaches content-suppressed, not dropped."""
    (temp_dir / "apm.yml").write_text(
        "name: t\nversion: 1.0.0\ndescription: Test\ntargets:\n  - cursor\n"
    )
    (temp_dir / ".apm" / "instructions").mkdir(parents=True)
    (temp_dir / ".cursor" / "rules").mkdir(parents=True)
    (temp_dir / ".cursor" / "rules" / "gen.mdc").write_text(
        "---\ndescription: Generated\n---\n\nUse the shared client.\n"
    )

    rules = RepositoryContext(temp_dir).lint_tree.find(CursorRuleBlock)
    assert [b.path.name for b in rules] == ["gen.mdc"]
    assert all(b.content_suppressed for b in rules)


def test_a_heading_mentioning_apm_does_not_drop_a_copilot_file(temp_dir):
    """The banner is an exact line, not a phrase on a comment-ish line.

    A Markdown heading starts with `#`, so a header-position check that
    accepted any comment-like line classified authored prose as output.
    """
    (temp_dir / "apm.yml").write_text(
        "name: t\nversion: 1.0.0\ndescription: Test\ntargets:\n  - copilot\n"
    )
    (temp_dir / ".apm" / "instructions").mkdir(parents=True)
    (temp_dir / ".apm" / "instructions" / "dev.instructions.md").write_text(
        "---\ndescription: Dev rules\n---\n\nRun the tests before pushing.\n"
    )
    (temp_dir / ".github").mkdir()
    (temp_dir / ".github" / "copilot-instructions.md").write_text(
        "# Review code generated by APM CLI before merging\n\nNever commit secrets.\n"
    )

    names = {b.path.name for b in RepositoryContext(temp_dir).lint_tree.find(InstructionBlock)}

    assert "copilot-instructions.md" in names


def test_a_nested_clinerules_file_is_linted(temp_dir):
    """The file form resolves from the workspace directory, like `.cursorrules`."""
    nested = temp_dir / "apps" / "web"
    nested.mkdir(parents=True)
    (nested / ".clinerules").write_text("Prefer the shared HTTP client.\n")

    context = RepositoryContext(temp_dir)
    paths = {b.path for b in context.lint_tree.find(InstructionBlock)}

    assert nested / ".clinerules" in paths
    assert "HAS_CLINE" in context.detected_formats


def test_prompt_identity_is_injective_across_the_separator():
    """Both identity components come from decoded JSON, so either can
    contain the NUL separator; concatenation alone let two different
    (path, line) pairs collide, and baselining one finding would then
    suppress the other."""
    a = CursorPromptHookBlock(
        path=Path("/r/h.json"), json_path="hooks.x", body="foo[0].prompt\x00zap"
    )
    b = CursorPromptHookBlock(
        path=Path("/r/h.json"), json_path="hooks.x\x00foo[0].prompt", body="zap"
    )

    assert a.fingerprint_identity(1) != b.fingerprint_identity(1)


def test_dot_labels_cannot_be_escaped_by_author_text(temp_dir):
    """A quoted DOT string must not be terminable by author text.

    `safe_display()` leaves a backslash alone, so quote-only escaping turned
    an authored `\\"` into `\\\\"` — one escaped backslash, then a quote that
    closes the label early. Everything after it became live graph syntax.
    The check walks each label string honouring escapes and asserts it
    closes exactly where the emitter's own attributes resume.
    """
    (temp_dir / ".cursor").mkdir()
    evil = 'x\\" ]; evil [label=PWN]; } //'
    (temp_dir / ".cursor" / "hooks.json").write_text(
        json.dumps({"version": 1, "hooks": {evil: [{"type": "prompt", "prompt": "Check."}]}})
    )

    dot = RepositoryContext(temp_dir).lint_tree.print_dot(root_path=temp_dir)

    label_lines = [ln for ln in dot.splitlines() if "[label=" in ln and "node [" not in ln]
    assert label_lines, dot
    for line in label_lines:
        start = line.index('[label="') + len('[label="')
        index = start
        while index < len(line):
            if line[index] == "\\":
                index += 2  # escaped character, whatever it is
                continue
            if line[index] == '"':
                break
            index += 1
        else:
            raise AssertionError(f"label never closes: {line}")
        # The string must close at the emitter's own attribute list — if
        # author text closed it early, graph syntax sits here instead.
        assert line[index:].startswith('" style=filled fillcolor='), line


def test_a_nested_cursorrules_is_linted(temp_dir):
    """Cursor reads the legacy file from the nearest enclosing directory."""
    nested = temp_dir / "apps" / "web"
    nested.mkdir(parents=True)
    (nested / ".cursorrules").write_text("Prefer the shared HTTP client.\n")
    (temp_dir / ".cursorrules").write_text("Use tabs in Makefiles.\n")

    context = RepositoryContext(temp_dir)
    paths = {b.path for b in context.lint_tree.find(InstructionBlock)}

    assert nested / ".cursorrules" in paths
    assert temp_dir / ".cursorrules" in paths
    # Detection must agree with attachment, or the Cursor rules never run.
    assert "HAS_CURSOR" in context.detected_formats


def test_a_nested_cursorrules_alone_activates_cursor(temp_dir):
    """A package-only legacy file is still Cursor configuration."""
    nested = temp_dir / "apps" / "web"
    nested.mkdir(parents=True)
    (nested / ".cursorrules").write_text("Prefer the shared HTTP client.\n")

    assert "HAS_CURSOR" in RepositoryContext(temp_dir).detected_formats


def test_an_excluded_editor_subdirectory_is_not_walked(temp_dir):
    """Excluding the directory must exclude what is inside it."""
    rules = temp_dir / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "a.mdc").write_text("---\ndescription: Rules\n---\n\nUse the client.\n")

    tree = RepositoryContext(temp_dir, exclude_patterns=[".cursor/rules"]).lint_tree

    assert tree.find(CursorRuleBlock) == []


def test_apm_compiled_root_copilot_instructions_is_content_suppressed(temp_dir):
    """`.apm/instructions/` compiles to the root Copilot file as well as the directory.

    The concatenated `copilot-instructions.md` sits beside the very sources
    it was built from, so its content and dedup findings are suppressed to
    avoid doubling them. It stays in the tree with ``content_suppressed`` set
    — dropping it entirely would blind the security rules to it — while its
    `.apm/instructions/` source is linted normally.
    """
    (temp_dir / "apm.yml").write_text(
        "name: t\nversion: 1.0.0\ndescription: Test\ntargets:\n  - copilot\n"
    )
    (temp_dir / ".apm" / "instructions").mkdir(parents=True)
    (temp_dir / ".apm" / "instructions" / "dev.instructions.md").write_text(
        "---\ndescription: Dev rules\n---\n\nRun the tests before pushing.\n"
    )
    (temp_dir / ".github").mkdir()
    (temp_dir / ".github" / "copilot-instructions.md").write_text(
        "<!-- Generated by APM CLI from .apm/ primitives -->\n\nRun the tests before pushing.\n"
    )

    blocks = {b.path.name: b for b in RepositoryContext(temp_dir).lint_tree.find(InstructionBlock)}

    assert "copilot-instructions.md" in blocks
    assert blocks["copilot-instructions.md"].content_suppressed
    assert "dev.instructions.md" in blocks
    assert not blocks["dev.instructions.md"].content_suppressed


def test_hand_written_root_copilot_instructions_still_linted(temp_dir):
    """No `.apm/instructions/` source means the root Copilot file is authored."""
    (temp_dir / "apm.yml").write_text(
        "name: t\nversion: 1.0.0\ndescription: Test\ntargets:\n  - copilot\n"
    )
    (temp_dir / ".apm" / "skills").mkdir(parents=True)
    (temp_dir / ".github").mkdir()
    (temp_dir / ".github" / "copilot-instructions.md").write_text(
        "# Copilot\n\nPrefer the repository's own helpers.\n"
    )

    names = {b.path.name for b in RepositoryContext(temp_dir).lint_tree.find(InstructionBlock)}

    assert "copilot-instructions.md" in names


def test_root_copilot_instructions_kept_when_apm_skips_copilot(temp_dir):
    """`targets:` without copilot means APM writes nothing into `.github/`."""
    (temp_dir / "apm.yml").write_text(
        "name: t\nversion: 1.0.0\ndescription: Test\ntargets:\n  - claude\n"
    )
    (temp_dir / ".apm" / "instructions").mkdir(parents=True)
    (temp_dir / ".apm" / "instructions" / "dev.instructions.md").write_text(
        "---\ndescription: Dev rules\n---\n\nRun the tests before pushing.\n"
    )
    (temp_dir / ".github").mkdir()
    (temp_dir / ".github" / "copilot-instructions.md").write_text(
        "# Copilot\n\nPrefer the repository's own helpers.\n"
    )

    names = {b.path.name for b in RepositoryContext(temp_dir).lint_tree.find(InstructionBlock)}

    assert "copilot-instructions.md" in names


def test_tree_finds_editor_tool_dirs_in_subpackages(temp_dir):
    """Cursor reads the nearest .cursor directory, so a monorepo package keeps its own."""
    nested = temp_dir / "apps" / "web" / ".cursor" / "rules"
    nested.mkdir(parents=True)
    (nested / "web.mdc").write_text("---\ndescription: Web rules\n---\n\nUse Tailwind.\n")

    tree = RepositoryContext(temp_dir).lint_tree

    assert [b.path.name for b in tree.find(CursorRuleBlock)] == ["web.mdc"]


def test_cursor_rule_role_wins_over_generic_instruction_symlink(temp_dir):
    """A generic alias must not suppress the target's specific parser role."""
    rules = temp_dir / ".cursor" / "rules"
    rules.mkdir(parents=True)
    target = rules / "unterminated.mdc"
    target.write_text("---\ndescription: Never parses\n\n# Unterminated\n")
    (temp_dir / "policy.instructions.md").symlink_to(target)

    context = RepositoryContext(temp_dir)
    tree = context.lint_tree

    assert [block.path for block in tree.find(CursorRuleBlock)] == [target]
    assert tree.find(InstructionBlock) == []
    violations = CursorRulesValidRule().check(context)
    assert len(violations) == 1
    assert "missing closing ---" in violations[0].message


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
