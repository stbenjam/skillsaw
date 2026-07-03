"""
Build the repository lint tree — single discovery entrypoint.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Set, TYPE_CHECKING

from .blocks import (
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
    PluginRuleBlock,
    PromptBlock,
    PromptfooPromptBlock,
    ReadmeBlock,
    SettingsBlock,
    SkillBlock,
    SkillRefBlock,
)
from .formats.promptfoo import (
    extract_file_refs,
    is_promptfoo_config,
    resolve_file_ref,
)
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

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .context import RepositoryContext


def build_lint_tree(context: "RepositoryContext") -> LintTarget:
    """Build a tree of all lintable objects in the repository."""
    _INSTRUCTION_FILE_BLOCK_TYPES = {
        "AGENTS.md": AgentsMdBlock,
        "CLAUDE.md": ClaudeMdBlock,
        "GEMINI.md": GeminiMdBlock,
    }

    root = LintTarget(path=context.root_path)
    seen: Set[Path] = set()

    _is_excluded = context.is_path_excluded
    _is_in_compiled_dir = context.in_apm_compiled_dir

    apm_source_root = (context.root_path / ".apm").resolve() if context.has_apm else None

    def _is_in_apm_source(p: Path) -> bool:
        if apm_source_root is None:
            return False
        resolved = p.resolve()
        return resolved == apm_source_root or resolved.is_relative_to(apm_source_root)

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

    # --- .claude/settings.json (supply-chain attack surface) ---
    _add_block(root, context.root_path / ".claude" / "settings.json", SettingsBlock)
    _add_block(root, context.root_path / ".claude" / "settings.local.json", SettingsBlock)

    # --- Root-level .mcp.json (MCP server configuration) ---
    _add_block(root, context.root_path / ".mcp.json", McpBlock)

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
        _add_block(plugin_node, plugin_path / "settings.json", SettingsBlock)
        _add_block(plugin_node, plugin_path / "settings.local.json", SettingsBlock)
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

        # Nearest plugin ancestor via dict lookups — iterating all plugins
        # with is_relative_to() is O(skills x plugins) and dominated tree
        # construction on large marketplaces (3.6k skills x 445 plugins).
        parent_plugin = None
        resolved_skill = skill_path.resolve()
        for candidate in (resolved_skill, *resolved_skill.parents):
            node = plugin_nodes.get(candidate)
            if node is not None:
                parent_plugin = node
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

    # --- Promptfoo prompt content blocks ---
    for block in PromptfooPromptBlock.gather_from_tree(root):
        block_resolved = block.path.resolve()
        for node in root.find(PromptfooConfigNode):
            if node.path.resolve() == block_resolved:
                node.children.append(block)
                break

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

        # Hooks and settings inside .apm/ (supply-chain attack surface)
        _add_block(apm_node, apm_dir / "hooks" / "hooks.json", HooksBlock)
        _add_block(apm_node, apm_dir / "settings.json", SettingsBlock)
        _add_block(apm_node, apm_dir / "settings.local.json", SettingsBlock)

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
    # User-configured content paths plus globs contributed by detected
    # plugin repo types; the ``seen`` set dedupes any overlap.
    for glob_pattern in [*context.content_paths, *context.plugin_content_paths]:
        try:
            matches = sorted(context.root_path.glob(glob_pattern))
        except (NotImplementedError, ValueError) as e:
            # Path.glob() rejects absolute patterns (NotImplementedError)
            # and some malformed ones (ValueError). The tree builds lazily
            # inside each rule's check(), so an invalid pattern — from user
            # config ``content-paths`` or a plugin repo type — would
            # otherwise surface as one rule-execution-error per rule.
            logger.warning("Ignoring invalid content path glob %r: %s", glob_pattern, e)
            continue
        for extra in matches:
            if extra.is_file():
                _add_block(root, extra, ExtraBlock)

    # --- Plugin tree contributors ---
    # Contributors return pre-constructed nodes (typically ContentBlock or
    # JsonConfigBlock subclasses), attached at the root. The ``seen`` set
    # guards against double-linting files already discovered above, and
    # failures are collected for the Linter to surface as violations —
    # a broken contributor must not abort tree construction.
    def _admit_contributed_node(block) -> bool:
        """Validate/dedupe a contributed node and its whole subtree.

        Contributors may return nodes with children; every descendant gets
        the same guards as top-level discovery (type check, ``seen`` dedupe,
        exclude patterns), with rejected descendants pruned in place.
        Returns False when the node itself must not be attached.
        """
        if not isinstance(block, LintTarget):
            raise TypeError(f"contributor returned {block!r}, which is not a lint tree node")
        resolved = block.path.resolve()
        if resolved in seen or not block.path.exists() or _is_excluded(block.path):
            return False
        seen.add(resolved)
        block.children = [child for child in block.children if _admit_contributed_node(child)]
        return True

    for plugin_name, contribute in context.plugin_tree_contributors:
        try:
            contributed = contribute(context, root)
            blocks = list(contributed) if contributed is not None else []
            # Attachment stays inside the try: a node with a broken path
            # (None, or resolve() raising an OSError) must be reported like
            # any other contributor failure, not crash tree construction.
            for block in blocks:
                if _admit_contributed_node(block):
                    root.children.append(block)
        except Exception as e:
            context.plugin_extension_errors.append(
                f"Plugin '{plugin_name}': tree contributor failed: " f"{e.__class__.__name__}: {e}"
            )
            continue

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
    from .utils import read_yaml

    config_nodes: list[PromptfooConfigNode] = []

    def _try_add_config(yaml_file: Path, parent: LintTarget, *, require_keys: bool = True) -> None:
        resolved = yaml_file.resolve()
        if resolved in seen or not yaml_file.exists() or _is_excluded(yaml_file):
            return
        if require_keys:
            data, error = read_yaml(yaml_file)
            if error or not is_promptfoo_config(data):
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

    # Pass 1a: promptfooconfig* anywhere in repo (naming convention → no key
    # check).  One pruned walk instead of two whole-repo rglobs — pruning
    # matches the repo-type detector, which already skips .git/node_modules/
    # .venv and friends.
    yaml_matches: list[Path] = []
    yml_matches: list[Path] = []
    for f in context._walk_files(context.root_path):
        if fnmatch.fnmatch(f.name, "promptfooconfig*.yaml"):
            yaml_matches.append(f)
        elif fnmatch.fnmatch(f.name, "promptfooconfig*.yml"):
            yml_matches.append(f)
    for yaml_file in sorted(yaml_matches) + sorted(yml_matches):
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
        for ref in extract_file_refs(data):
            resolved = resolve_file_ref(ref, config_dir, root=context.root_path)
            if resolved is None or resolved in seen:
                continue
            if not resolved.exists() or _is_excluded(Path(resolved)):
                continue
            seen.add(resolved)
            frag = PromptfooConfigNode(path=Path(resolved), is_fragment=True)
            config_node.children.append(frag)
