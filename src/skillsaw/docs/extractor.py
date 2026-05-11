"""Extract structured documentation content from a repository."""

from __future__ import annotations

from typing import List, Optional

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.docs.models import (
    AgentDoc,
    CommandDoc,
    DocsOutput,
    HookDoc,
    HookEntry,
    MarketplaceDoc,
    McpServerDoc,
    PluginDoc,
    RuleFileDoc,
    SkillDoc,
)
from skillsaw.lint_target import PluginNode, SkillNode
from skillsaw.rules.builtin.content_analysis import (
    AgentBlock,
    CommandBlock,
    HooksBlock,
    McpBlock,
    PluginRuleBlock,
    ReadmeBlock,
    SkillBlock,
)


def extract_docs(
    context: RepositoryContext,
    title: Optional[str] = None,
) -> DocsOutput:
    """Extract documentation from a repository context."""
    plugins = [_extract_plugin(context, pn) for pn in context.lint_tree.find(PluginNode)]

    marketplace = None
    if RepositoryType.MARKETPLACE in context.repo_types and context.marketplace_data:
        md = context.marketplace_data
        marketplace = MarketplaceDoc(
            name=md.get("name", ""),
            owner=md.get("owner"),
            plugins=plugins,
        )

    standalone_skills: List[SkillDoc] = []
    if RepositoryType.AGENTSKILLS in context.repo_types:
        plugin_skill_paths = {s.dir_path.resolve() for p in plugins for s in p.skills}
        for skill_node in context.lint_tree.find(SkillNode):
            if skill_node.path.resolve() not in plugin_skill_paths:
                doc = _extract_skill(skill_node)
                if doc:
                    standalone_skills.append(doc)

    resolved_title = title or _default_title(context, marketplace, plugins)

    return DocsOutput(
        repo_type=context.repo_type,
        title=resolved_title,
        marketplace=marketplace,
        plugins=plugins,
        skills=standalone_skills,
    )


def _default_title(
    context: RepositoryContext,
    marketplace: Optional[MarketplaceDoc],
    plugins: List[PluginDoc],
) -> str:
    if marketplace and marketplace.name:
        return marketplace.name
    if RepositoryType.DOT_CLAUDE in context.repo_types:
        return ""
    if len(plugins) == 1 and plugins[0].name:
        return plugins[0].name
    return context.repo_type.value.replace("-", " ").title() + " Documentation"


def _extract_plugin(context: RepositoryContext, plugin_node: PluginNode) -> PluginDoc:
    plugin_path = plugin_node.path
    meta = context.get_plugin_metadata(plugin_path) or {}
    name = context.get_plugin_name(plugin_path)

    author_val = meta.get("author")
    if isinstance(author_val, str):
        author_val = {"name": author_val}

    return PluginDoc(
        name=name,
        path=plugin_path,
        description=meta.get("description", ""),
        version=str(v) if (v := meta.get("version")) is not None else "",
        author=author_val if isinstance(author_val, dict) else None,
        commands=_extract_commands(plugin_node),
        skills=_extract_skills(plugin_node),
        agents=_extract_agents(plugin_node),
        hooks=_extract_hooks(plugin_node),
        mcp_servers=_extract_mcp_servers(plugin_node, meta),
        rules=_extract_rules(plugin_node),
        has_readme=bool(plugin_node.find(ReadmeBlock)),
    )


# -- Commands --


def _extract_commands(plugin_node: PluginNode) -> List[CommandDoc]:
    docs = []
    for block in plugin_node.find(CommandBlock):
        fm = block.frontmatter or {}
        name_lines = block.section("Name").strip().splitlines()
        full_name = name_lines[0] if name_lines else ""
        synopsis = _strip_fences(block.section("Synopsis"))
        body_text = block.section("Description")
        docs.append(
            CommandDoc(
                name=block.path.stem,
                file_path=block.path,
                description=fm.get("description", ""),
                full_name=full_name,
                synopsis=synopsis,
                body=body_text,
            )
        )
    return sorted(docs, key=lambda d: d.name)


# -- Skills --


def _extract_skills(plugin_node: PluginNode) -> List[SkillDoc]:
    docs = []
    for skill_node in plugin_node.find(SkillNode):
        doc = _extract_skill(skill_node)
        if doc:
            docs.append(doc)
    return sorted(docs, key=lambda d: d.name)


def _extract_skill(skill_node: SkillNode) -> Optional[SkillDoc]:
    blocks = skill_node.find(SkillBlock)
    if not blocks:
        return None
    block = blocks[0]
    fm = block.frontmatter
    if fm is None:
        fm = {}

    allowed_tools = fm.get("allowed-tools", [])
    if isinstance(allowed_tools, str):
        allowed_tools = [allowed_tools]
    if not isinstance(allowed_tools, list):
        allowed_tools = []

    return SkillDoc(
        name=fm.get("name", skill_node.path.name),
        dir_path=skill_node.path,
        description=fm.get("description", ""),
        license=fm.get("license", ""),
        compatibility=fm.get("compatibility", ""),
        metadata=fm.get("metadata", {}),
        allowed_tools=allowed_tools or [],
        body=block.body_text.strip(),
    )


# -- Agents --


def _extract_agents(plugin_node: PluginNode) -> List[AgentDoc]:
    docs = []
    for block in plugin_node.find(AgentBlock):
        fm = block.frontmatter or {}
        docs.append(
            AgentDoc(
                name=fm.get("name", block.path.stem),
                file_path=block.path,
                description=fm.get("description", ""),
                body=block.body_text.strip(),
            )
        )
    return sorted(docs, key=lambda d: d.name)


# -- Hooks --


def _extract_hooks(plugin_node: PluginNode) -> List[HookDoc]:
    docs = []
    for block in plugin_node.find(HooksBlock):
        for event_type in sorted(block.events):
            configs = block.events[event_type]
            entries = [
                HookEntry(
                    matcher=cfg.matcher,
                    hooks=[
                        {k: v for k, v in h.__dict__.items() if v is not None and k != "type"}
                        | {"type": h.type}
                        for h in cfg.handlers
                    ],
                )
                for cfg in configs
            ]
            if entries:
                docs.append(HookDoc(event_type=event_type, entries=entries))
    return docs


# -- MCP Servers --


def _extract_mcp_servers(plugin_node: PluginNode, plugin_meta: dict) -> List[McpServerDoc]:
    servers: List[McpServerDoc] = []
    seen: set = set()

    for block in plugin_node.find(McpBlock):
        for srv in block.servers:
            servers.append(
                McpServerDoc(
                    name=srv.name,
                    server_type=srv.type,
                    config={k: v for k, v in srv.__dict__.items() if v is not None and k != "name"},
                    source_file=".mcp.json",
                )
            )
            seen.add(srv.name)

    mcp_in_plugin = plugin_meta.get("mcpServers", {})
    if isinstance(mcp_in_plugin, dict):
        for name, cfg in mcp_in_plugin.items():
            if name in seen or not isinstance(cfg, dict):
                continue
            servers.append(
                McpServerDoc(
                    name=name,
                    server_type=cfg.get("type", "stdio"),
                    config=cfg,
                    source_file="plugin.json",
                )
            )
    return servers


# -- Rules --


def _extract_rules(plugin_node: PluginNode) -> List[RuleFileDoc]:
    docs = []
    for block in plugin_node.find(PluginRuleBlock):
        fm = block.frontmatter or {}
        globs: List[str] = []
        paths = fm.get("paths", [])
        if isinstance(paths, list):
            globs = [str(p) for p in paths]
        docs.append(
            RuleFileDoc(
                name=block.path.stem,
                file_path=block.path,
                description=fm.get("description", ""),
                globs=globs,
                body=block.body_text.strip(),
            )
        )
    return sorted(docs, key=lambda d: d.name)


# -- Helpers --


def _strip_fences(text: str) -> str:
    """Remove leading/trailing code fences from a block."""
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return text.strip()
