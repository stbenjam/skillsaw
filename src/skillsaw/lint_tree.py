"""
Build the repository lint tree — single discovery entrypoint.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Set, TYPE_CHECKING

logger = logging.getLogger(__name__)

from .lint_target import (
    LintTarget,
    ApmConfigNode,
    ApmNode,
    MarketplaceConfigNode,
    MarketplaceNode,
    PluginNode,
    PromptfooConfigNode,
    SkillNode,
    CodeRabbitNode,
)

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
        HooksBlock,
        InstructionBlock,
        McpBlock,
        ReadmeBlock,
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

    apm_source_root = (context.root_path / ".apm").resolve() if context.has_apm else None

    def _is_in_apm_source(p: Path) -> bool:
        if apm_source_root is None:
            return False
        resolved = p.resolve()
        return resolved == apm_source_root or resolved.is_relative_to(apm_source_root)

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

    # --- Root-level instruction files (skip .apm/ — handled in APM section) ---
    for f in context.instruction_files:
        if _is_in_apm_source(f):
            continue
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

    # --- Marketplace config ---
    marketplace_json = context.root_path / ".claude-plugin" / "marketplace.json"
    if marketplace_json.exists() and not _is_excluded(marketplace_json):
        root.children.append(MarketplaceConfigNode(path=marketplace_json))

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

        _add_block(plugin_node, plugin_path / "hooks" / "hooks.json", HooksBlock)
        _add_block(plugin_node, plugin_path / ".mcp.json", McpBlock)
        _add_block(plugin_node, plugin_path / "README.md", ReadmeBlock)

        plugin_nodes[plugin_path.resolve()] = plugin_node
        if marketplace_node is not None and plugin_path.resolve().is_relative_to(
            marketplace_dir.resolve()
        ):
            marketplace_node.children.append(plugin_node)
        else:
            root.children.append(plugin_node)

    # --- Skills (nest inside parent plugin when applicable; skip .apm/) ---
    for skill_path in context.skills:
        if _is_in_apm_source(skill_path):
            continue
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

    # --- Promptfoo eval configs ---
    _build_promptfoo_nodes(context, root, plugin_nodes, seen, _is_excluded)

    # --- APM ---
    if context.has_apm:
        apm_yml = context.root_path / "apm.yml"
        if apm_yml.exists() and not _is_excluded(apm_yml):
            root.children.append(ApmConfigNode(path=apm_yml))

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

        apm_skills = apm_dir / "skills"
        if apm_skills.is_dir():
            for skill_path in context.skills:
                if skill_path.resolve().is_relative_to(apm_skills.resolve()):
                    skill_node = SkillNode(path=skill_path)
                    _add_block(skill_node, skill_path / "SKILL.md", SkillBlock)
                    refs_dir = skill_path / "references"
                    if refs_dir.is_dir():
                        for ref_file in sorted(refs_dir.glob("*.md")):
                            _add_block(skill_node, ref_file, SkillRefBlock)
                    apm_node.children.append(skill_node)

        root.children.append(apm_node)

    # --- Extra content paths from config ---
    for glob_pattern in getattr(context, "content_paths", []):
        for extra in sorted(context.root_path.glob(glob_pattern)):
            if extra.is_file():
                _add_block(root, extra, ExtraBlock)

    root.set_parents()
    nodes = list(root.walk())
    logger.info("Built lint tree: %d nodes", len(nodes))
    return root


def _build_promptfoo_nodes(
    context: "RepositoryContext",
    root: LintTarget,
    plugin_nodes: dict,
    seen: Set[Path],
    _is_excluded,
) -> None:
    """Discover promptfoo config files and build PromptfooConfigNode nodes.

    Pass 1: find confirmed configs (promptfooconfig* naming or evals/ with promptfoo keys).
    Pass 2: resolve file:// refs from confirmed configs and add fragments as children.
    """
    from .rules.builtin.promptfoo import (
        _is_promptfoo_config,
        _extract_file_refs,
        _resolve_file_ref,
    )
    from .rules.builtin.utils import read_yaml

    config_nodes: list[PromptfooConfigNode] = []

    def _try_add_config(yaml_file: Path, parent: LintTarget, *, require_keys: bool = True) -> None:
        resolved = yaml_file.resolve()
        if resolved in seen or not yaml_file.exists() or _is_excluded(yaml_file):
            return
        if require_keys:
            data, error = read_yaml(yaml_file)
            if error or not _is_promptfoo_config(data):
                return
        seen.add(resolved)
        node = PromptfooConfigNode(path=yaml_file)
        parent.children.append(node)
        config_nodes.append(node)

    def _scan_evals_dir(evals_dir: Path, parent: LintTarget) -> None:
        if not evals_dir.is_dir():
            return
        for pattern in ("*.yaml", "*.yml"):
            for yaml_file in sorted(evals_dir.rglob(pattern)):
                _try_add_config(yaml_file, parent, require_keys=True)

    # Pass 1a: promptfooconfig* at repo root (promptfoo naming → no key check)
    for pattern in ("promptfooconfig*.yaml", "promptfooconfig*.yml"):
        for yaml_file in sorted(context.root_path.glob(pattern)):
            _try_add_config(yaml_file, root, require_keys=False)

    # Pass 1b: evals/ at repo root
    _scan_evals_dir(context.root_path / "evals", root)

    # Pass 1c: evals/ inside plugins and skills
    for node in list(root.walk()):
        if not isinstance(node, (PluginNode, SkillNode)):
            continue
        _scan_evals_dir(node.path / "evals", node)

    # Pass 2: resolve file:// refs from confirmed configs → fragment children
    for config_node in config_nodes:
        data, error = read_yaml(config_node.path)
        if error or not isinstance(data, dict):
            continue
        config_dir = config_node.path.parent
        for ref in _extract_file_refs(data):
            resolved = _resolve_file_ref(ref, config_dir)
            if resolved is None or resolved in seen:
                continue
            if not resolved.exists():
                continue
            seen.add(resolved)
            frag = PromptfooConfigNode(path=Path(resolved), is_fragment=True)
            config_node.children.append(frag)
