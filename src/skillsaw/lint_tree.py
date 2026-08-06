"""
Build the repository lint tree — single discovery entrypoint.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Set, TYPE_CHECKING, Tuple

from .blocks import (
    AgentBlock,
    AgentPluginMcpBlock,
    AgentsMdBlock,
    ChatmodeBlock,
    ClaudeMdBlock,
    CodeRabbitContentBlock,
    CodexInlineHooksBlock,
    CodexInlineMcpBlock,
    CommandBlock,
    ContextFileBlock,
    CursorRuleBlock,
    ExtraBlock,
    GeminiMdBlock,
    HooksBlock,
    InstructionBlock,
    McpBlock,
    OpenAIMetadataBlock,
    PluginRuleBlock,
    PromptBlock,
    PromptfooPromptBlock,
    ReadmeBlock,
    SettingsBlock,
    SkillBlock,
    SkillRefBlock,
)
from .formats.codex import (
    codex_declared_hook_files,
    codex_declared_mcp_files,
    codex_inline_hooks,
    codex_inline_mcp_servers,
)
from .paths import contained_resolve, safe_exists, safe_is_dir, safe_is_file, safe_resolve
from .formats.promptfoo import (
    extract_file_refs,
    is_promptfoo_config,
    resolve_file_ref,
)
from .lint_target import (
    AgentPluginConfigNode,
    AgentPluginNode,
    LintTarget,
    ApmConfigNode,
    ApmNode,
    CodexMarketplaceConfigNode,
    CodexPluginConfigNode,
    CodexPluginNode,
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
    repo_root = safe_resolve(context.root_path)
    if repo_root is None:
        message = f"Repository root could not be resolved: {context.root_path}"
        if message not in context.lint_tree_errors:
            context.lint_tree_errors.append(message)
        logger.error(message)
        root.set_parents()
        return root
    seen: Set[Path] = set()
    seen_roles: Set[Tuple[Path, type]] = set()
    openai_seen: Set[Tuple[Path, Path]] = set()

    _is_excluded = context.is_path_excluded
    _is_in_compiled_dir = context.in_apm_compiled_dir

    def _resolve_repo_path(path: Path) -> Path | None:
        """Resolve *path* only when the repository root and containment are safe."""
        if repo_root is None:
            return None
        return contained_resolve(path, repo_root)

    apm_source_root = (
        (safe_resolve((context.root_path / ".apm")) or (context.root_path / ".apm"))
        if context.has_apm
        else None
    )

    def _is_in_apm_source(p: Path) -> bool:
        """Return whether *p* belongs to the active APM source tree."""
        if apm_source_root is None:
            return False
        resolved = safe_resolve(p) or p
        return resolved == apm_source_root or resolved.is_relative_to(apm_source_root)

    def _add_block(
        parent: LintTarget,
        p: Path,
        block_cls: type,
        owner: Path | None = None,
    ) -> None:
        """Add one safely resolved block unless its role is already present."""
        resolved = _resolve_repo_path(p)
        if resolved is None or resolved in seen or not safe_exists(resolved) or _is_excluded(p):
            return
        seen.add(resolved)
        seen_roles.add((resolved, block_cls))
        block = block_cls(path=p)
        block.plugin_owner = owner
        parent.children.append(block)

    def _add_parser_block(
        parent: LintTarget,
        p: Path,
        block_cls: type,
        owner: Path | None = None,
    ) -> None:
        """Attach a structured document once for each parser role.

        A JSON document may legitimately contain both hooks and MCP servers.
        Path-only deduplication would hide whichever parser runs second, while
        role-aware deduplication still prevents duplicate findings when two
        discovery paths select the same parser.
        """
        resolved = _resolve_repo_path(p)
        if resolved is None:
            return
        role = (resolved, block_cls)
        if role in seen_roles or not safe_is_file(resolved) or _is_excluded(p):
            return
        # seen_roles only — never the path-only ``seen`` set: a manifest can
        # declare ``hooks``/``mcpServers`` at any in-plugin markdown file,
        # and poisoning ``seen`` would drop that file from every content
        # rule that attaches later.
        seen_roles.add(role)
        block = block_cls(path=p)
        block.plugin_owner = owner
        parent.children.append(block)

    # Nearest package ownership, with the roots resolved once per context.
    _contained_plugin_owner = context.contained_plugin_owning
    agent_plugin_roots = set(context.agent_plugin_roots())

    def _shadowed_by_agent_plugin_mcp(path: Path, agent_plugin_mcp: Path | None) -> bool:
        """Whether *path* is the portable ``mcp.json`` under another name.

        A dual-format package may symlink ``.mcp.json`` (or declare a Codex
        MCP file) at the portable ``mcp.json``. That document is already
        attached once as the Agent Plugins parser role, so a second parser
        role here would duplicate every policy and security finding.
        """
        return agent_plugin_mcp is not None and safe_resolve(path) == agent_plugin_mcp

    def _add_contained_plugin_block(
        parent: CodexPluginConfigNode | AgentPluginConfigNode,
        p: Path,
        block_cls: type,
        owner: Path | None = None,
    ) -> None:
        """Role-aware block attachment for a path that must stay inside its plugin.

        Conventional package files can be found without a manifest path
        declaration, so nothing else has checked where they resolve to. A
        symlink would otherwise read an external file under an in-repo path.
        """
        root = safe_resolve(parent.plugin_dir)
        resolved = safe_resolve(p)
        if root is None or resolved is None or not resolved.is_relative_to(root):
            return
        _add_parser_block(parent, p, block_cls, owner=owner)

    def _add_plugin_prose(parent: LintTarget, plugin_dir: Path, owner: Path) -> None:
        """The one prose attach for every plugin container.

        ``commands/``, ``agents/``, ``rules/`` and README follow the same
        conventions across plugin ecosystems, so every claimed directory gets
        them here — the content and security rules must read this prose
        whoever owns it. Containment as in ``_add_contained_plugin_block``: a symlink
        would pull an external file under an in-repo name.
        """
        plugin_resolved = safe_resolve(plugin_dir)
        if plugin_resolved is None:
            return

        def _contained(p: Path) -> bool:
            """Inside this plugin, and not inside a nested claimed plugin.

            Any claimed plugin directory strictly between the file and this
            plugin's root means the file is the nested plugin's to attach —
            otherwise a repo-root plugin's recursive ``rules/`` scan would
            tag nested files with the outer owner and poison ``seen`` first.
            ``seen_plugin_dirs`` is fully populated before the plugin loop
            makes the first call here.
            """
            resolved = safe_resolve(p)
            if resolved is None:
                return False
            for ancestor in resolved.parents:
                if ancestor == plugin_resolved:
                    return True
                if ancestor in seen_plugin_dirs:
                    return False
            return False

        for dirname, block_cls, pattern in (
            ("commands", CommandBlock, "*.md"),
            ("agents", AgentBlock, "*.md"),
            ("rules", PluginRuleBlock, "**/*.md"),
        ):
            content_dir = plugin_dir / dirname
            if not safe_is_dir(content_dir):
                continue
            try:
                files = sorted(content_dir.glob(pattern))
            except OSError:
                continue
            for md in files:
                if _contained(md):
                    _add_block(parent, md, block_cls, owner=owner)
        readme = plugin_dir / "README.md"
        if _contained(readme):
            _add_block(parent, readme, ReadmeBlock, owner=owner)

    def _add_openai_metadata(
        parent: LintTarget,
        path: Path,
        *,
        metadata_root: Path,
        containment_root: Path,
    ) -> None:
        """Attach structured OpenAI metadata."""
        # Existence first: this runs once per SkillNode, and `agents/
        # openai.yaml` is absent in the overwhelming majority of them — the
        # three resolves below cost a realpath each and answer nothing when
        # there is no file to attach.
        if not safe_is_file(path) or _is_excluded(path):
            return
        resolved = safe_resolve(path)
        root = safe_resolve(containment_root)
        owner = safe_resolve(metadata_root)
        if (
            resolved is None
            or root is None
            or owner is None
            or (resolved, owner) in openai_seen
            or not resolved.is_relative_to(root)
        ):
            return
        # Metadata paths have owner-relative semantics, so the same contained
        # file may need validation once for each skill that links to it. Keep
        # this separate from the content-block dedupe set for the same reason.
        openai_seen.add((resolved, owner))
        block = OpenAIMetadataBlock(
            path=path,
            metadata_root=metadata_root,
            containment_root=containment_root,
        )
        parent.children.append(block)

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
    # A dual-format package may symlink both conventional paths to one file.
    # Prefer the portable parser role so ecosystem-neutral policy rules see
    # the executable surface once rather than reporting duplicate findings.
    root_agent_plugin_mcp = (
        safe_resolve(context.root_path / "mcp.json") if repo_root in agent_plugin_roots else None
    )
    root_native_mcp = context.root_path / ".mcp.json"
    if not _shadowed_by_agent_plugin_mcp(root_native_mcp, root_agent_plugin_mcp):
        _add_block(root, root_native_mcp, McpBlock)

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

    # --- Codex marketplace configs ---
    # Not filtered by _is_in_compiled_dir even though ".agents" is an APM
    # compiled root: APM generates .agents/skills/ and friends, never
    # .agents/plugins/marketplace.json, which is hand-authored.
    for codex_marketplace_json in context.codex_marketplace_paths():
        if not _is_excluded(codex_marketplace_json):
            root.children.append(CodexMarketplaceConfigNode(path=codex_marketplace_json))

    # --- Plugins (build first so skills can nest inside them) ---
    plugin_nodes: dict[Path, PluginNode] = {}
    codex_plugin_nodes: dict[Path, CodexPluginNode] = {}
    agent_plugin_nodes: dict[Path, AgentPluginNode] = {}
    marketplace_dir = context.root_path / "plugins"
    marketplace_node: MarketplaceNode | None = None
    if (context.has_marketplace() or context.has_codex_marketplace()) and marketplace_dir.is_dir():
        marketplace_node = MarketplaceNode(path=marketplace_dir)
        root.children.append(marketplace_node)

    # --- Plugins: one pass over every claimed directory ---
    # Exactly one container per directory, with prose and config attached
    # from its provenance. Never add per-ecosystem loops: two loops that
    # must complement each other exactly are how a directory falls between
    # attach paths and loses its content silently.
    plugin_dirs: list[Path] = []
    seen_plugin_dirs: set[Path] = set()
    # Catalog claims join the union: a local source with no manifest and no
    # legacy marker is still a claimed directory whose hooks, prose, and
    # skills the rules must see. The claim set is resolved and contained
    # already.
    for candidate in (
        *context.plugins,
        *context.codex_plugins,
        *context.agent_plugins,
        *sorted(p for p in context._codex_claim_set() if not context.is_path_excluded(p)),
        *sorted(p for p in context._agent_plugin_claim_set() if not context.is_path_excluded(p)),
    ):
        resolved_candidate = safe_resolve(candidate)
        if resolved_candidate is None:
            # A claim that cannot resolve (symlink loop, unreadable
            # parent) must not abort tree construction for the whole
            # repository.
            continue
        if resolved_candidate in seen_plugin_dirs:
            continue
        if not safe_is_dir(candidate):
            # A dangling catalog claim names no directory to lint;
            # codex-marketplace-registration reports the entry itself.
            continue
        seen_plugin_dirs.add(resolved_candidate)
        plugin_dirs.append(candidate)

    root_plugin_owner: Path | None = None
    for plugin_path in plugin_dirs:
        prov = context.provenance(plugin_path)
        # Compiled-output filtering is a Claude/APM concept; a Codex claim
        # is its own provenance and keeps the directory.
        if _is_in_compiled_dir(plugin_path) and not prov.codex:
            continue
        resolved_plugin = safe_resolve(plugin_path)
        if resolved_plugin is None:
            continue

        is_agent_plugin = resolved_plugin in agent_plugin_roots
        agent_plugin_mcp = safe_resolve(plugin_path / "mcp.json") if is_agent_plugin else None

        # Container type: Claude identity keeps PluginNode and its Claude
        # rules. Otherwise Codex wins the neutral hierarchy choice when a
        # package declares both non-Claude formats; each format still gets
        # its own config node below the one shared container. Root packages
        # hang directly off the tree root.
        container: LintTarget
        if prov.claude:
            container = PluginNode(path=plugin_path)
            plugin_nodes[resolved_plugin] = container
        elif resolved_plugin == root.resolved_path and (prov.codex or is_agent_plugin):
            container = root
        elif prov.codex:
            container = CodexPluginNode(path=plugin_path)
            codex_plugin_nodes[resolved_plugin] = container
        elif is_agent_plugin:
            container = AgentPluginNode(path=plugin_path)
            agent_plugin_nodes[resolved_plugin] = container
        else:
            # Legacy unclaimed directories discovered by the Claude layout
            # retain their established container and validation behavior.
            container = PluginNode(path=plugin_path)
            plugin_nodes[resolved_plugin] = container

        if container is not root:
            container.plugin_owner = resolved_plugin
        else:
            # A repo-root package shares conventional config paths with the
            # repository, so ownership is decided here once.
            root_plugin_owner = resolved_plugin
            # Only ``.mcp.json`` needs re-tagging: the generic root attach
            # never adds a HooksBlock (hooks/hooks.json attaches under the
            # Codex cluster with containment).
            claimed = {safe_resolve(plugin_path / ".mcp.json")} - {None}
            for child in root.children:
                if isinstance(child, McpBlock) and safe_resolve(child.path) in claimed:
                    child.plugin_owner = resolved_plugin

        _add_plugin_prose(container, plugin_path, resolved_plugin)

        # Conventional Claude configs belong only to Claude or legacy
        # unclaimed packages. Portable-only packages must not accidentally
        # inherit Claude's hooks, .mcp.json, or settings semantics.
        if prov.claude or (not prov.ecosystems and not is_agent_plugin):
            _add_block(
                container, plugin_path / "hooks" / "hooks.json", HooksBlock, owner=resolved_plugin
            )
            native_mcp = plugin_path / ".mcp.json"
            if not _shadowed_by_agent_plugin_mcp(native_mcp, agent_plugin_mcp):
                _add_block(container, native_mcp, McpBlock, owner=resolved_plugin)
        # settings.json is Claude-side configuration with no Codex
        # counterpart: attached only for Claude-style directories, keeping
        # _add_block's bare resolve() away from content a hostile
        # Codex-only checkout controls.
        if prov.claude or (not prov.ecosystems and not is_agent_plugin):
            _add_block(
                container, plugin_path / "settings.json", SettingsBlock, owner=resolved_plugin
            )
            _add_block(
                container, plugin_path / "settings.local.json", SettingsBlock, owner=resolved_plugin
            )

        # Codex manifest cluster, for any directory Codex claims (dual
        # directories hang it off their PluginNode).
        if prov.codex:
            manifest = plugin_path.joinpath(*context.CODEX_PLUGIN_MANIFEST)
            # Not gated on the manifest existing: a plugin whose manifest is
            # missing must still reach codex-plugin-json-valid to be
            # reported. An excluded manifest is no plugin-wide skip either —
            # hooks and MCP files carry executable commands and have their
            # own exclusion checks; the linter filters violations filed
            # against the excluded manifest itself.
            node = CodexPluginConfigNode(path=manifest)
            node.plugin_owner = resolved_plugin
            _add_openai_metadata(
                node,
                plugin_path / "agents" / "openai.yaml",
                metadata_root=plugin_path,
                containment_root=plugin_path,
            )
            # Codex "checks that default file automatically", so a plugin
            # can ship executable hooks without declaring them — the same
            # supply-chain surface as a Claude plugin's hooks.
            _add_contained_plugin_block(
                node, plugin_path / "hooks" / "hooks.json", HooksBlock, owner=resolved_plugin
            )
            # A manifest may point ``hooks`` at other files, or write them
            # inline; both carry the same executable commands. Inline
            # payloads have no file of their own, so they borrow the
            # manifest path.
            for declared_hooks in codex_declared_hook_files(plugin_path):
                _add_parser_block(node, declared_hooks, HooksBlock, owner=resolved_plugin)
            for inline_hooks in codex_inline_hooks(plugin_path):
                inline_block = CodexInlineHooksBlock(path=manifest, inline_data=inline_hooks)
                inline_block.plugin_owner = resolved_plugin
                node.children.append(inline_block)
            # Same treatment for MCP: the conventional .mcp.json, declared
            # files, and inline maps are all commands the host will spawn.
            native_mcp = plugin_path / ".mcp.json"
            if not _shadowed_by_agent_plugin_mcp(native_mcp, agent_plugin_mcp):
                _add_contained_plugin_block(node, native_mcp, McpBlock, owner=resolved_plugin)
            for declared_mcp in codex_declared_mcp_files(plugin_path):
                if _shadowed_by_agent_plugin_mcp(declared_mcp, agent_plugin_mcp):
                    continue
                _add_parser_block(node, declared_mcp, McpBlock, owner=resolved_plugin)
            for inline_mcp in codex_inline_mcp_servers(plugin_path):
                inline_block = CodexInlineMcpBlock(path=manifest, inline_data=inline_mcp)
                inline_block.plugin_owner = resolved_plugin
                node.children.append(inline_block)
            container.children.append(node)

        # Agent Plugins manifest cluster. A forced ``--type agent-plugin``
        # seeds this even when plugin.json is absent, so the validity rule can
        # report the missing entrypoint. The optional mcp.json is attached
        # only when it is a contained regular file; malformed path/kind cases
        # remain visible to the config rule through the manifest node.
        if is_agent_plugin:
            node = AgentPluginConfigNode(path=plugin_path / "plugin.json")
            node.plugin_owner = resolved_plugin
            _add_contained_plugin_block(
                node,
                plugin_path / "mcp.json",
                AgentPluginMcpBlock,
                owner=resolved_plugin,
            )
            container.children.append(node)

        if container is not root:
            if marketplace_node is not None and resolved_plugin.is_relative_to(
                (safe_resolve(marketplace_dir) or marketplace_dir)
            ):
                marketplace_node.children.append(container)
            else:
                root.children.append(container)

    # --- Skills (nest inside parent plugin when applicable; skip .apm/) ---
    for skill_path in context.skills:
        if _is_in_apm_source(skill_path):
            continue
        skill_node = SkillNode(path=skill_path)
        _add_block(skill_node, skill_path / "SKILL.md", SkillBlock)
        # Contained against the owning package: rules both read and
        # rewrite these files, so a symlink here is a read *and* a write
        # outside the checkout.
        ref_root = _contained_plugin_owner(skill_path)

        _add_openai_metadata(
            skill_node,
            skill_path / "agents" / "openai.yaml",
            metadata_root=skill_path,
            containment_root=ref_root or skill_path,
        )

        def _contained_in_plugin(candidate: Path, ref_root: Path | None = ref_root) -> bool:
            if ref_root is None:
                return True
            resolved = safe_resolve(candidate)
            return resolved is not None and resolved.is_relative_to(ref_root)

        refs_dir = skill_path / "references"
        if refs_dir.is_dir():
            for ref_file in sorted(refs_dir.glob("*.md")):
                if _contained_in_plugin(ref_file):
                    _add_block(skill_node, ref_file, SkillRefBlock)

        # Nearest plugin ancestor via dict lookups — iterating all plugins
        # with is_relative_to() is O(skills x plugins) and dominated tree
        # construction on large marketplaces (3.6k skills x 445 plugins).
        parent_plugin: LintTarget | None = None
        resolved_skill = safe_resolve(skill_path) or skill_path
        for candidate in (resolved_skill, *resolved_skill.parents):
            node = (
                plugin_nodes.get(candidate)
                or codex_plugin_nodes.get(candidate)
                or agent_plugin_nodes.get(candidate)
            )
            if node is not None:
                parent_plugin = node
                skill_node.plugin_owner = candidate
                break
        if parent_plugin is not None:
            parent_plugin.children.append(skill_node)
        else:
            # A repo-root package has no container of its own, so its
            # skills hang off the tree root; the ownership tag keeps them
            # attributable to the plugin all the same.
            skill_node.plugin_owner = root_plugin_owner
            root.children.append(skill_node)

    # --- .coderabbit.yaml ---
    cr_path = context.root_path / ".coderabbit.yaml"
    cr_resolved = _resolve_repo_path(cr_path)
    if cr_resolved is not None and safe_exists(cr_resolved) and not _is_excluded(cr_path):
        cr_container = CodeRabbitNode(path=cr_path)
        cr_blocks = CodeRabbitContentBlock.gather(context, seen, _is_excluded)
        cr_container.children.extend(cr_blocks)
        root.children.append(cr_container)

    # --- Promptfoo eval configs ---
    _build_promptfoo_nodes(context, root, plugin_nodes, seen, _is_excluded)

    # --- Promptfoo prompt content blocks ---
    for block in PromptfooPromptBlock.gather_from_tree(root):
        block_resolved = safe_resolve(block.path) or block.path
        for node in root.find(PromptfooConfigNode):
            if (safe_resolve(node.path) or node.path) == block_resolved:
                node.children.append(block)
                break

    # --- APM ---
    if context.has_apm:
        apm_yml = context.root_path / "apm.yml"
        if apm_yml.exists() and not _is_excluded(apm_yml):
            root.children.append(ApmConfigNode(path=apm_yml))

        # `.apm/` holds a package's authored primitives. A consumer-only
        # manifest — `apm.yml` with `dependencies:`/`targets:` and no
        # authored content — has no `.apm/` directory, so don't invent an
        # ApmNode for a path that doesn't exist (issue #472).
        apm_dir = context.root_path / ".apm"
        if apm_dir.is_dir():
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
                    if (safe_resolve(skill_path) or skill_path).is_relative_to(
                        (safe_resolve(apm_skills) or apm_skills)
                    ):
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
            if not extra.is_file():
                continue
            extra_resolved = safe_resolve(extra)
            if extra_resolved is not None and any(
                claimed == extra_resolved for claimed, _ in seen_roles
            ):
                # Already attached under a structured parser role (hooks,
                # MCP): re-attaching it as prose would make every
                # content-quality rule lint structured config as text.
                continue
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
        if not isinstance(block.path, Path):
            raise TypeError(f"contributor returned a node with invalid path {block.path!r}")
        resolved = _resolve_repo_path(block.path)
        if resolved is None:
            raise ValueError(f"contributor path is unresolved or outside repository: {block.path}")
        if resolved in seen or not safe_exists(resolved) or _is_excluded(block.path):
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
    repo_root = safe_resolve(context.root_path)

    def _try_add_config(yaml_file: Path, parent: LintTarget, *, require_keys: bool = True) -> None:
        """Add a contained Promptfoo config that satisfies discovery rules."""
        resolved = contained_resolve(yaml_file, repo_root) if repo_root is not None else None
        if (
            resolved is None
            or resolved in seen
            or not safe_is_file(resolved)
            or _is_excluded(yaml_file)
        ):
            return
        if require_keys:
            data, error = read_yaml(resolved)
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
            if not safe_exists(resolved) or _is_excluded(Path(resolved)):
                continue
            seen.add(resolved)
            frag = PromptfooConfigNode(path=Path(resolved), is_fragment=True)
            config_node.children.append(frag)
