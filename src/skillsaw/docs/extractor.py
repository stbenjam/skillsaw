"""Extract structured documentation content from a repository."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formats.codex import codex_local_source_path, safe_resolve
from skillsaw.utils import read_json
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
from skillsaw.blocks import (
    AgentBlock,
    CommandBlock,
    HooksBlock,
    McpBlock,
    PluginRuleBlock,
    ReadmeBlock,
    SkillBlock,
)
from skillsaw.lint_target import CodexPluginConfigNode, LintTarget, PluginNode, SkillNode


def extract_docs(
    context: RepositoryContext,
    title: Optional[str] = None,
) -> DocsOutput:
    """Extract documentation from a repository context."""
    # A PluginNode with no Claude manifest but a Codex one is a Codex plugin
    # that legacy discovery picked up for its commands/ or skills/ directory.
    # _extract_codex_plugins handles it, and reading it through the Claude
    # extractor as well would list it twice with empty metadata.
    plugins = [
        _extract_plugin(context, pn)
        for pn in context.lint_tree.find(PluginNode)
        if not _is_codex_only(context, pn.path)
    ]
    plugins.extend(_extract_codex_plugins(context))

    marketplace = None
    if RepositoryType.MARKETPLACE in context.repo_types and context.marketplace_data:
        md = context.marketplace_data
        # Codex remote-only entries have no lint-tree node, so they are not
        # in ``plugins`` and would be dropped entirely when a Claude
        # marketplace supplies the catalog identity.
        marketplace = MarketplaceDoc(
            name=md.get("name", ""),
            owner=md.get("owner"),
            plugins=plugins + _codex_remote_docs(context, {p.name for p in plugins}),
        )
    elif RepositoryType.CODEX_MARKETPLACE in context.repo_types:
        # ``marketplace_data`` only ever loads .claude-plugin/marketplace.json,
        # so a Codex catalog needs its own MarketplaceDoc to reach the
        # multi-page renderer.
        marketplace = _codex_marketplace_doc(context, plugins)

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


def _is_codex_only(context: RepositoryContext, plugin_path: Path) -> bool:
    """Whether *plugin_path* is a Codex plugin with no Claude identity."""
    if (plugin_path / ".claude-plugin" / "plugin.json").is_file():
        return False
    resolved = safe_resolve(plugin_path)
    if resolved is not None and resolved in getattr(context, "marketplace_entries", {}):
        return False
    return plugin_path.joinpath(*context.CODEX_PLUGIN_MANIFEST).is_file()


def _codex_marketplace_doc(
    context: RepositoryContext, plugins: List[PluginDoc]
) -> Optional[MarketplaceDoc]:
    """A MarketplaceDoc built from the Codex catalog.

    Codex catalogs carry no ``owner`` — the field has no equivalent in the
    schema — so only the name is read across. The first catalog wins when a
    repository splits its listing across siblings, matching how
    codex-marketplace-registration picks the primary.
    """
    name: Optional[str] = None
    for path in context.codex_marketplace_paths():
        data, error = read_json(path)
        if error or not isinstance(data, dict):
            continue
        name = str(data.get("name", "") or "")
        break
    if name is None:
        return None
    remote = _codex_remote_docs(context, {p.name for p in plugins})
    return MarketplaceDoc(name=name, owner=None, plugins=plugins + remote)


def _codex_remote_docs(context: RepositoryContext, local_names: set) -> List[PluginDoc]:
    """Remote-entry docs from every discovered Codex catalog.

    A repository can split its listing across sibling files, and a
    remote-only entry in any of them has no local directory and so no
    lint-tree node — nothing else would find it.
    """
    docs: List[PluginDoc] = []
    for path in context.codex_marketplace_paths():
        data, error = read_json(path)
        if error or not isinstance(data, dict):
            continue
        docs.extend(_remote_entry_docs(data, local_names))
    return docs


# Source types that name something outside this repository. Anything else
# claiming to be local, but without a usable path, is malformed rather than
# remote.
_REMOTE_SOURCE_TYPES = {"url", "git-subdir", "npm"}


def _is_remote_source(source: Any) -> bool:
    return isinstance(source, dict) and source.get("source") in _REMOTE_SOURCE_TYPES


def _remote_entry_docs(data: dict, local_names: set) -> List[PluginDoc]:
    """Metadata-only docs for catalog entries with no local directory.

    A ``url``, ``git-subdir`` or ``npm`` source is not checked out here, so
    no CodexPluginConfigNode exists for it and it would be missing from the
    rendered catalog entirely — leaving the index reporting fewer plugins
    than the catalog lists. What the entry itself declares is enough to
    list it.
    """
    entries = data.get("plugins")
    if not isinstance(entries, list):
        return []
    docs: List[PluginDoc] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name or name in local_names:
            continue
        source = entry.get("source")
        if codex_local_source_path(source) is not None:
            continue  # local entry — the real plugin was extracted above
        if not _is_remote_source(source):
            # ``{"source": "local"}`` with no path, or an empty one, is a
            # broken local entry rather than a remote one. Codex skips it
            # and codex-marketplace-json-valid reports it; publishing a page
            # for it would advertise a plugin that cannot be installed.
            continue
        local_names.add(name)
        docs.append(
            PluginDoc(
                name=name,
                path=Path(name),
                description=str(entry.get("description", "") or ""),
                version=str(v) if (v := entry.get("version")) is not None else "",
                category=str(entry.get("category", "") or ""),
            )
        )
    return docs


def _extract_codex_plugins(context: RepositoryContext) -> List[PluginDoc]:
    """Plugin docs for Codex plugins that carry no Claude manifest.

    A dual-ecosystem plugin already has a ``PluginNode`` and is documented
    through it, so it is skipped here to avoid a duplicate entry. A
    Codex-only plugin has nothing but its ``CodexPluginConfigNode``, and
    without this ``skillsaw docs`` emitted no plugin metadata, hooks or MCP
    servers for a repository it had just classified as ``codex-plugin``.
    """
    # A PluginNode alone does not mean a Claude plugin: legacy discovery
    # creates one for any directory with commands/ or skills/. Only a real
    # Claude manifest, or a marketplace entry claiming it, means the Claude
    # extractor can read its metadata — otherwise the docs fall back to the
    # directory name and lose everything the Codex manifest declares.
    claude_dirs = {
        pn.path.resolve()
        for pn in context.lint_tree.find(PluginNode)
        if not _is_codex_only(context, pn.path)
    }
    docs: List[PluginDoc] = []
    # Resolved once for the whole catalog rather than once per plugin:
    # matching skills by path is O(plugins x skills) stat calls otherwise,
    # and a large catalog has hundreds of each.
    skill_nodes = [(safe_resolve(n.path), n) for n in context.lint_tree.find(SkillNode)]
    resolved_skills = [(r, n) for r, n in skill_nodes if r is not None]

    for node in context.lint_tree.find(CodexPluginConfigNode):
        plugin_resolved = safe_resolve(node.plugin_dir)
        if not node.path.is_file() or plugin_resolved is None or plugin_resolved in claude_dirs:
            continue
        if context.is_codex_installed_plugin(node.plugin_dir):
            # A personal install under .codex/plugins/. Publishing it as a
            # member of the repository's catalog would misattribute someone
            # else's plugin — the same authorship line the registration and
            # manifest-quality rules already draw.
            continue
        legacy = [
            pn
            for pn in context.lint_tree.find(PluginNode)
            if safe_resolve(pn.path) == plugin_resolved
        ]
        docs.append(_extract_codex_plugin(context, node, plugin_resolved, resolved_skills, legacy))
    return docs


class _BlockSources:
    """Several tree nodes searched as one for `find()`."""

    def __init__(self, nodes):
        self._nodes = nodes

    def find(self, block_cls):
        out = []
        for node in self._nodes:
            out.extend(node.find(block_cls))
        return out


def _extract_codex_plugin(
    context: RepositoryContext,
    node: CodexPluginConfigNode,
    plugin_resolved: Path,
    resolved_skills: List[Tuple[Path, SkillNode]],
    legacy_nodes: List[PluginNode],
) -> PluginDoc:
    """Build a PluginDoc from a Codex manifest and its subtree.

    The Codex manifest carries the same descriptive fields as a Claude one,
    so the shape of the output is unchanged. Commands, agents and rule
    files are always empty: Codex plugins ship skills, hooks and MCP
    servers, and have no equivalent of those three.
    """
    plugin_dir = node.plugin_dir
    meta = _read_json_dict(node)
    # When legacy discovery also built a PluginNode for this directory — it
    # does for any plugin shipping commands/ — that node claimed hooks.json
    # and .mcp.json first, and the lint tree's ``seen`` set kept them off
    # the Codex node. Both are searched so neither placement loses them.
    sources = _BlockSources([node, *legacy_nodes])

    author_val = meta.get("author")
    if isinstance(author_val, str):
        author_val = {"name": author_val}

    return PluginDoc(
        name=context.codex_plugin_name(plugin_dir),
        path=plugin_dir,
        description=str(meta.get("description", "") or ""),
        version=str(v) if (v := meta.get("version")) is not None else "",
        author=author_val if isinstance(author_val, dict) else None,
        display_name=_interface_field(meta, "displayName"),
        category=_interface_field(meta, "category") or str(meta.get("category", "") or ""),
        tags=_string_list(meta.get("tags")),
        keywords=_string_list(meta.get("keywords")),
        homepage=str(meta.get("homepage", "") or ""),
        repository=str(meta.get("repository", "") or ""),
        license=str(meta.get("license", "") or ""),
        commands=[],
        skills=_extract_codex_skills(plugin_resolved, resolved_skills),
        agents=[],
        hooks=_extract_hooks(sources),
        # meta is passed empty: the manifest's own ``mcpServers`` map is
        # already in the tree as a CodexInlineMcpBlock, and feeding it here
        # too would list every inline server twice.
        mcp_servers=_extract_mcp_servers(sources, {}),
        rules=[],
        has_readme=(plugin_dir / "README.md").is_file(),
    )


def _read_json_dict(node: CodexPluginConfigNode) -> dict:
    data, error = read_json(node.path)
    return data if not error and isinstance(data, dict) else {}


def _interface_field(meta: dict, key: str) -> str:
    """Codex keeps presentation fields under ``interface``."""
    interface = meta.get("interface")
    if isinstance(interface, dict):
        return str(interface.get(key, "") or "")
    return ""


def _string_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v]


def _extract_codex_skills(
    plugin_resolved: Path, resolved_skills: List[Tuple[Path, SkillNode]]
) -> List[SkillDoc]:
    """Skills living under the plugin directory.

    A Codex-only plugin has no ``PluginNode`` for its skills to nest
    inside, so they hang off the tree root and have to be matched back by
    path rather than by subtree. Both sides arrive pre-resolved — see the
    caller for why.
    """
    docs = []
    for skill_resolved, skill_node in resolved_skills:
        if not skill_resolved.is_relative_to(plugin_resolved):
            continue
        doc = _extract_skill(skill_node)
        if doc:
            docs.append(doc)
    return sorted(docs, key=lambda d: d.name)


def _extract_plugin(context: RepositoryContext, plugin_node: PluginNode) -> PluginDoc:
    plugin_path = plugin_node.path
    meta = context.get_plugin_metadata(plugin_path) or {}
    name = context.get_plugin_name(plugin_path)

    author_val = meta.get("author")
    if isinstance(author_val, str):
        author_val = {"name": author_val}

    tags = meta.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags if t]

    keywords = meta.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k) for k in keywords if k]

    return PluginDoc(
        name=name,
        path=plugin_path,
        description=meta.get("description", ""),
        version=str(v) if (v := meta.get("version")) is not None else "",
        author=author_val if isinstance(author_val, dict) else None,
        display_name=str(meta.get("displayName", "")) or "",
        category=str(meta.get("category", "")) or "",
        tags=tags,
        keywords=keywords,
        homepage=str(meta.get("homepage", "")) or "",
        repository=str(meta.get("repository", "")) or "",
        license=str(meta.get("license", "")) or "",
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
        name_lines = block.section("Name").strip().splitlines()
        full_name = name_lines[0] if name_lines else ""
        synopsis = _strip_fences(block.section("Synopsis"))
        body_text = block.section("Description")
        docs.append(
            CommandDoc(
                name=block.path.stem,
                file_path=block.path,
                description=block.field_value("description", ""),
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

    allowed_tools = block.field_value("allowed-tools", [])
    if isinstance(allowed_tools, str):
        allowed_tools = [allowed_tools]
    if not isinstance(allowed_tools, list):
        allowed_tools = []

    return SkillDoc(
        name=block.field_value("name", skill_node.path.name),
        dir_path=skill_node.path,
        description=block.field_value("description", ""),
        license=block.field_value("license", ""),
        compatibility=block.field_value("compatibility", ""),
        metadata=block.field_value("metadata", {}),
        allowed_tools=allowed_tools or [],
        body=block.body_text.strip(),
    )


# -- Agents --


def _extract_agents(plugin_node: PluginNode) -> List[AgentDoc]:
    docs = []
    for block in plugin_node.find(AgentBlock):
        docs.append(
            AgentDoc(
                name=block.field_value("name", block.path.stem),
                file_path=block.path,
                description=block.field_value("description", ""),
                body=block.body_text.strip(),
            )
        )
    return sorted(docs, key=lambda d: d.name)


# -- Hooks --


def _extract_hooks(plugin_node: LintTarget) -> List[HookDoc]:
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


def _extract_mcp_servers(plugin_node: LintTarget, plugin_meta: dict) -> List[McpServerDoc]:
    servers: List[McpServerDoc] = []
    seen: set = set()

    for block in plugin_node.find(McpBlock):
        # Not hard-coded: a Codex manifest can point ``mcpServers`` at
        # another file, or hold the map itself — in which case the block
        # borrows the manifest's path and the source really is plugin.json.
        source_file = block.path.name
        for srv in block.servers:
            servers.append(
                McpServerDoc(
                    name=srv.name,
                    server_type=srv.type,
                    config={k: v for k, v in srv.__dict__.items() if v is not None and k != "name"},
                    source_file=source_file,
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
        globs: List[str] = []
        paths = block.field_value("paths", [])
        if isinstance(paths, list):
            globs = [str(p) for p in paths]
        docs.append(
            RuleFileDoc(
                name=block.path.stem,
                file_path=block.path,
                description=block.field_value("description", ""),
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
