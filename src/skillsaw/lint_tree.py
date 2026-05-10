"""
Build the repository lint tree — single discovery entrypoint.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Set, TYPE_CHECKING

from .lint_target import LintTarget, ApmNode, MarketplaceNode, PluginNode, SkillNode, CodeRabbitNode

if TYPE_CHECKING:
    from .context import RepositoryContext


def build_lint_tree(context: "RepositoryContext") -> LintTarget:
    """Build a tree of all lintable objects in the repository."""
    from .rules.builtin.content_analysis import (
        AgentBlock,
        AgentsMdBlock,
        ChatmodeBlock,
        ClaudeMdBlock,
        CodeRabbitContentBlock,
        CommandBlock,
        ContextFileBlock,
        CursorRuleBlock,
        ExtraBlock,
        GeminiMdBlock,
        InstructionBlock,
        PluginRuleBlock,
        PromptBlock,
        SkillBlock,
        SkillRefBlock,
    )

    _INSTRUCTION_FILE_BLOCK_TYPES = {
        "AGENTS.md": AgentsMdBlock,
        "CLAUDE.md": ClaudeMdBlock,
        "GEMINI.md": GeminiMdBlock,
    }

    root = LintTarget(path=context.root_path)
    seen: Set[Path] = set()
    exclude = getattr(context, "exclude_patterns", [])
    resolved_root = context.root_path.resolve()

    apm_compiled_roots: Set[Path] = set()
    if context.has_apm:
        from .context import RepositoryContext as _RC

        for compiled_dir_name in _RC.APM_COMPILED_DIRS:
            compiled_path = (context.root_path / compiled_dir_name).resolve()
            if compiled_path.is_dir():
                apm_compiled_roots.add(compiled_path)

    def _is_excluded(p: Path) -> bool:
        if not exclude:
            return False
        try:
            rel = str(p.resolve().relative_to(resolved_root))
        except ValueError:
            return False
        return any(fnmatch.fnmatch(rel, pat) for pat in exclude)

    def _is_in_compiled_dir(p: Path) -> bool:
        if not apm_compiled_roots:
            return False
        resolved = p.resolve()
        return any(resolved == excl or resolved.is_relative_to(excl) for excl in apm_compiled_roots)

    def _add_block(
        parent: LintTarget,
        p: Path,
        block_cls: type,
    ) -> None:
        resolved = p.resolve()
        if resolved in seen or not p.exists() or _is_excluded(p):
            return
        seen.add(resolved)
        parent.children.append(block_cls(path=p))

    # --- Root-level instruction files ---
    for f in context.instruction_files:
        block_cls = _INSTRUCTION_FILE_BLOCK_TYPES.get(f.name, InstructionBlock)
        _add_block(root, f, block_cls)

    _add_block(root, context.root_path / ".github" / "copilot-instructions.md", InstructionBlock)
    _add_block(root, context.root_path / ".cursorrules", InstructionBlock)

    cursor_rules_dir = context.root_path / ".cursor" / "rules"
    if cursor_rules_dir.is_dir() and not _is_in_compiled_dir(cursor_rules_dir):
        for mdc in sorted(cursor_rules_dir.glob("*.mdc")):
            _add_block(root, mdc, CursorRuleBlock)

    kiro_steering = context.root_path / ".kiro" / "steering"
    if kiro_steering.is_dir():
        for md in sorted(kiro_steering.glob("*.md")):
            _add_block(root, md, InstructionBlock)

    _add_block(root, context.root_path / ".windsurfrules", InstructionBlock)

    clinerules = context.root_path / ".clinerules"
    if clinerules.is_file():
        _add_block(root, clinerules, InstructionBlock)
    elif clinerules.is_dir():
        for md in sorted(clinerules.glob("*.md")):
            _add_block(root, md, InstructionBlock)

    # --- Plugins (build first so skills can nest inside them) ---
    plugin_nodes: dict[Path, PluginNode] = {}
    marketplace_dir = context.root_path / "plugins"
    marketplace_node: MarketplaceNode | None = None
    if context.has_marketplace() and marketplace_dir.is_dir():
        marketplace_node = MarketplaceNode(path=marketplace_dir)
        root.children.append(marketplace_node)

    for plugin_path in context.plugins:
        if _is_in_compiled_dir(plugin_path):
            continue
        plugin_node = PluginNode(path=plugin_path)

        commands_dir = plugin_path / "commands"
        if commands_dir.is_dir():
            for cmd_file in sorted(commands_dir.glob("*.md")):
                _add_block(plugin_node, cmd_file, CommandBlock)

        agents_dir = plugin_path / "agents"
        if agents_dir.is_dir():
            for agent_file in sorted(agents_dir.glob("*.md")):
                _add_block(plugin_node, agent_file, AgentBlock)

        rules_dir = plugin_path / "rules"
        if rules_dir.is_dir():
            for rule_file in sorted(rules_dir.rglob("*.md")):
                _add_block(plugin_node, rule_file, PluginRuleBlock)

        plugin_nodes[plugin_path.resolve()] = plugin_node
        if marketplace_node is not None and plugin_path.resolve().is_relative_to(
            marketplace_dir.resolve()
        ):
            marketplace_node.children.append(plugin_node)
        else:
            root.children.append(plugin_node)

    # --- Skills (nest inside parent plugin when applicable) ---
    for skill_path in context.skills:
        skill_node = SkillNode(path=skill_path)
        _add_block(skill_node, skill_path / "SKILL.md", SkillBlock)
        refs_dir = skill_path / "references"
        if refs_dir.is_dir():
            for ref_file in sorted(refs_dir.glob("*.md")):
                _add_block(skill_node, ref_file, SkillRefBlock)

        parent_plugin = None
        for plugin_resolved, plugin_node in plugin_nodes.items():
            if skill_path.resolve().is_relative_to(plugin_resolved):
                parent_plugin = plugin_node
                break
        if parent_plugin is not None:
            parent_plugin.children.append(skill_node)
        else:
            root.children.append(skill_node)

    # --- .coderabbit.yaml ---
    cr_path = context.root_path / ".coderabbit.yaml"
    if cr_path.exists() and not _is_excluded(cr_path):
        cr_container = CodeRabbitNode(path=cr_path)
        cr_blocks = CodeRabbitContentBlock.gather(context, seen, _is_excluded)
        cr_container.children.extend(cr_blocks)
        root.children.append(cr_container)

    # --- APM source directories ---
    if context.has_apm:
        apm_dir = context.root_path / ".apm"
        apm_node = ApmNode(path=apm_dir)

        apm_instructions = apm_dir / "instructions"
        if apm_instructions.is_dir():
            for md in sorted(apm_instructions.glob("*.instructions.md")):
                _add_block(apm_node, md, InstructionBlock)

        apm_agents = apm_dir / "agents"
        if apm_agents.is_dir():
            for md in sorted(apm_agents.glob("*.agent.md")):
                _add_block(apm_node, md, AgentBlock)

        apm_prompts = apm_dir / "prompts"
        if apm_prompts.is_dir():
            for md in sorted(apm_prompts.glob("*.md")):
                _add_block(apm_node, md, PromptBlock)

        apm_chatmodes = apm_dir / "chatmodes"
        if apm_chatmodes.is_dir():
            for md in sorted(apm_chatmodes.glob("*.md")):
                _add_block(apm_node, md, ChatmodeBlock)

        apm_context = apm_dir / "context"
        if apm_context.is_dir():
            for md in sorted(apm_context.glob("*.md")):
                _add_block(apm_node, md, ContextFileBlock)

        root.children.append(apm_node)

    # --- Extra content paths from config ---
    for glob_pattern in getattr(context, "content_paths", []):
        for extra in sorted(context.root_path.glob(glob_pattern)):
            if extra.is_file():
                _add_block(root, extra, ExtraBlock)

    return root
