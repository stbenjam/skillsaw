"""Extract structured documentation content from a repository."""

from __future__ import annotations

import html

from pathlib import Path
from typing import Any, List, Optional, Set
from urllib.parse import urlsplit

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formats.codex import (
    codex_local_source_path,
    codex_plugin_name,
    is_remote_source,
)
from skillsaw.paths import safe_is_file, safe_resolve
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
    name_str,
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
from skillsaw.lint_target import (
    AgentPluginConfigNode,
    CodexPluginConfigNode,
    LintTarget,
    PluginNode,
    SkillNode,
)


def extract_docs(
    context: RepositoryContext,
    title: Optional[str] = None,
) -> DocsOutput:
    """Extract documentation from a repository context."""
    # A PluginNode with a Codex manifest but no Claude one belongs to
    # _extract_codex_plugins; reading it through the Claude extractor as
    # well would list it twice with empty metadata.
    codex_roots = _codex_roots(context)
    claude_plugins = [
        _extract_plugin(context, pn)
        for pn in context.lint_tree.find(PluginNode)
        if not _is_codex_only(context, pn.path, codex_roots)
    ]
    codex_plugins = _extract_codex_plugins(context)
    plugins = claude_plugins + codex_plugins
    # A portable Agent Plugins package that another ecosystem also claims is
    # already documented above: its AgentPluginConfigNode hangs off the same
    # container, so the portable mcp.json, skills and prose are in that doc.
    # Only a package no other ecosystem claims needs its own extraction —
    # without it the package is absent entirely and its skills surface as
    # standalone repository content.
    documented = {r for p in plugins if (r := safe_resolve(p.path)) is not None}
    plugins = plugins + _extract_agent_plugins(context, documented)

    marketplace = None
    if RepositoryType.MARKETPLACE in context.repo_types and context.marketplace_data:
        md = context.marketplace_data
        # A mixed repository has two independent catalogs: Claude docs are
        # governed by the Claude marketplace, Codex-only docs are filtered
        # and enriched through the Codex catalog — otherwise an
        # unregistered Codex directory appears merely because discovery
        # found it. Remote-only Codex entries have no lint-tree node and
        # must be added from the catalog.
        listed = claude_plugins + _codex_listed_docs(context, codex_plugins)
        marketplace = MarketplaceDoc(
            name=md.get("name", ""),
            owner=md.get("owner"),
            plugins=listed + _codex_remote_docs(context, {name_str(p.name) for p in listed}),
        )
    elif RepositoryType.CODEX_MARKETPLACE in context.repo_types:
        # ``marketplace_data`` only ever loads the Claude marketplace, so a
        # Codex catalog needs its own MarketplaceDoc.
        marketplace = _codex_marketplace_doc(context, plugins)

    standalone_skills: List[SkillDoc] = []
    if RepositoryType.AGENTSKILLS in context.repo_types:
        plugin_skill_paths = {
            (safe_resolve(s.dir_path) or s.dir_path) for p in plugins for s in p.skills
        }
        # An installed plugin's skills match no PluginDoc, and the
        # standalone pass would publish someone else's skills as this
        # repository's own top-level content.
        installed_roots = [
            r
            for p in context.codex_plugins
            if context.is_codex_installed_plugin(p) and (r := safe_resolve(p)) is not None
        ]
        for skill_node in context.lint_tree.find(SkillNode):
            resolved = safe_resolve(skill_node.path)
            if resolved is None or resolved in plugin_skill_paths:
                continue
            if any(resolved.is_relative_to(root) for root in installed_roots):
                continue
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


def _codex_roots(context: RepositoryContext) -> Set[Path]:
    """Return the context's cached, resolved Codex plugin roots."""
    return set(context.codex_plugin_roots())


def _is_codex_only(context: RepositoryContext, plugin_path: Path, codex_roots: Set[Path]) -> bool:
    """Whether *plugin_path* is a Codex plugin with no Claude identity.

    Keyed on what discovery actually accepted, not a raw ``is_file()``:
    that follows a symlink out of the plugin, so a rejected manifest would
    still mark the directory Codex-only and drop the plugin from the docs.
    """
    resolved = safe_resolve(plugin_path)
    if resolved is None:
        return False
    return resolved in codex_roots and context.is_codex_only_plugin(plugin_path)


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
    listed = _codex_listed_docs(context, plugins)
    remote = _codex_remote_docs(context, {name_str(p.name) for p in listed})
    return MarketplaceDoc(name=name, owner=None, plugins=listed + remote)


def _codex_listed_docs(context: RepositoryContext, plugins: List[PluginDoc]) -> List[PluginDoc]:
    """The extracted docs the catalog actually lists, in catalog order.

    Membership is what the catalog's ``plugins`` array says, not what
    discovery happened to find — publishing every discovered plugin listed
    ``.claude/`` itself as a catalog entry on dot-claude repositories.

    A listing's ``category`` is overlaid onto the matched doc: the field
    frequently lives only in the catalog, and reading the manifest alone
    left locally-sourced plugins missing from the rendered category filter.
    """
    by_path = {r: p for p in plugins if (r := safe_resolve(p.path)) is not None}
    codex_roots = _codex_roots(context)
    listed: List[PluginDoc] = []
    seen: Set[int] = set()
    for path in context.codex_marketplace_paths():
        data, error = read_json(path)
        if error or not isinstance(data, dict):
            continue
        entries = data.get("plugins")
        if not isinstance(entries, list):
            continue  # codex-marketplace-json-valid reports the shape
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source = codex_local_source_path(entry.get("source"))
            if source is None:
                continue  # remote or malformed — _codex_remote_docs decides
            resolved = safe_resolve(context.root_path / source)
            if resolved is None or resolved not in codex_roots:
                # A listed directory without a usable Codex manifest: Codex
                # cannot install it, and publishing it would advertise what
                # the catalog cannot deliver. Dual-host plugins are Codex
                # roots and stay listed.
                continue
            doc = by_path.get(resolved)
            if doc is None or id(doc) in seen:
                continue
            seen.add(id(doc))
            category = entry.get("category")
            if isinstance(category, str) and category and not doc.category:
                doc.category = category
            listed.append(doc)
    return listed


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


def _remote_entry_docs(data: dict, local_names: set) -> List[PluginDoc]:
    """Metadata-only docs for catalog entries with no local directory.

    A ``url``, ``git-subdir`` or ``npm`` source is not checked out here, so
    no CodexPluginConfigNode exists for it; what the entry itself declares
    is enough to list it.
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
        if not is_remote_source(source):
            # ``{"source": "local"}`` with no path is a broken local entry,
            # not a remote one — publishing a page for it would advertise a
            # plugin that cannot be installed.
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
    through it; skipping it here avoids a duplicate entry. A Codex-only
    plugin has nothing but its ``CodexPluginConfigNode``.
    """
    # A PluginNode alone does not mean a Claude plugin — legacy discovery
    # creates one for any directory with commands/ or skills/, and reading
    # such a directory through the Claude extractor would lose everything
    # the Codex manifest declares.
    codex_roots = _codex_roots(context)
    claude_dirs = {
        (safe_resolve(pn.path) or pn.path)
        for pn in context.lint_tree.find(PluginNode)
        if not _is_codex_only(context, pn.path, codex_roots)
    }
    docs: List[PluginDoc] = []
    for node in context.lint_tree.find(CodexPluginConfigNode):
        # The tree's ownership decision, read back rather than re-derived
        # from the path.
        plugin_resolved = node.plugin_owner
        if not node.path.is_file() or plugin_resolved is None or plugin_resolved in claude_dirs:
            continue
        if context.is_codex_installed_plugin(node.plugin_dir):
            # A personal install under .codex/plugins/ — publishing it in
            # the repository's catalog would misattribute someone else's
            # plugin.
            continue
        docs.append(_extract_codex_plugin(context, node, plugin_resolved))
    return docs


def _owned_blocks(
    context: RepositoryContext,
    node: LintTarget,
    block_cls: type,
    plugin_resolved: Path,
) -> list:
    """Blocks the tree assigned to this plugin, the manifest subtree first.

    Prose attaches to the plugin's container, config to the manifest node,
    and a repo-root plugin's conventional ``.mcp.json`` to the tree root —
    all carry the ``plugin_owner`` tag the build recorded, so one owner
    scan finds every placement. The manifest subtree is listed first (and
    deduplicated by identity) to keep the established document order.
    """
    blocks = node.find(block_cls)
    have = {id(b) for b in blocks}
    blocks.extend(
        b
        for b in context.lint_tree.find(block_cls)
        if id(b) not in have and b.plugin_owner == plugin_resolved
    )
    return blocks


def _extract_codex_plugin(
    context: RepositoryContext,
    node: CodexPluginConfigNode,
    plugin_resolved: Path,
) -> PluginDoc:
    """Build a PluginDoc from a Codex manifest and its subtree.

    The Codex manifest carries the same descriptive fields as a Claude
    one, so the shape of the output is unchanged; commands, agents and
    rule files attach when the plugin ships them.
    """
    plugin_dir = node.plugin_dir
    meta = _read_json_dict(node)

    author_val = meta.get("author")
    if isinstance(author_val, str):
        author_val = {"name": author_val}

    return PluginDoc(
        name=codex_plugin_name(plugin_dir),
        path=plugin_dir,
        description=str(meta.get("description", "") or ""),
        version=str(v) if (v := meta.get("version")) is not None else "",
        author=author_val if isinstance(author_val, dict) else None,
        display_name=_interface_field(meta, "displayName"),
        category=_interface_field(meta, "category") or str(meta.get("category", "") or ""),
        tags=_string_list(meta.get("tags")),
        keywords=_string_list(meta.get("keywords")),
        homepage=_safe_url(meta.get("homepage")),
        repository=_safe_url(meta.get("repository")),
        license=str(meta.get("license", "") or ""),
        **_owned_components(context, node, plugin_resolved),
        has_readme=(plugin_dir / "README.md").is_file(),
    )


def _owned_components(
    context: RepositoryContext,
    node: LintTarget,
    plugin_resolved: Path,
) -> dict:
    """The component docs the tree assigned to a manifest-rooted plugin.

    Every manifest ecosystem places its content the same way — prose on the
    container, config under the manifest node — and tags all of it with the
    owning root, so one owner scan serves Codex and Agent Plugins alike.
    """
    return dict(
        commands=_command_docs(_owned_blocks(context, node, CommandBlock, plugin_resolved)),
        skills=_extract_owned_skills(context, plugin_resolved),
        agents=_agent_docs(_owned_blocks(context, node, AgentBlock, plugin_resolved)),
        hooks=_extract_hooks(_owned_blocks(context, node, HooksBlock, plugin_resolved)),
        # meta is passed empty: a manifest's own ``mcpServers`` map is
        # already in the tree as an inline block — feeding it here too
        # would list every inline server twice.
        mcp_servers=_extract_mcp_servers(
            _owned_blocks(context, node, McpBlock, plugin_resolved), {}
        ),
        rules=_rule_docs(_owned_blocks(context, node, PluginRuleBlock, plugin_resolved)),
    )


def _extract_agent_plugins(
    context: RepositoryContext,
    documented: Set[Path],
) -> List[PluginDoc]:
    """Plugin docs for portable packages no other ecosystem documents.

    Both package layouts land here: a repo-root package, whose container is
    the tree root, and a ``plugins/*`` collection member under an
    ``AgentPluginNode``. Neither has a ``PluginNode`` or Codex manifest of
    its own, so the ``AgentPluginConfigNode`` is the only thing that names
    the package.
    """
    docs: List[PluginDoc] = []
    for node in context.lint_tree.find(AgentPluginConfigNode):
        # The tree's ownership decision, read back rather than re-derived.
        plugin_resolved = node.plugin_owner or safe_resolve(node.plugin_dir)
        if plugin_resolved is None or plugin_resolved in documented:
            continue
        documented.add(plugin_resolved)
        docs.append(_extract_agent_plugin(context, node, plugin_resolved))
    return docs


def _extract_agent_plugin(
    context: RepositoryContext,
    node: AgentPluginConfigNode,
    plugin_resolved: Path,
) -> PluginDoc:
    """Build a PluginDoc from an Agent Plugins manifest and its subtree.

    The manifest is read defensively: ``--type agent-plugin`` seeds this
    node even when plugin.json is missing or unparseable, and
    agent-plugin-json-valid is what reports that — documentation stays
    total and falls back to the directory name.
    """
    plugin_dir = node.plugin_dir
    meta = _read_json_dict(node)

    author_val = meta.get("author")
    if isinstance(author_val, str):
        author_val = {"name": author_val}

    name = meta.get("name")
    return PluginDoc(
        # Agent Plugins 1.0.0 declares no displayName, category or tags —
        # the fields stay empty rather than being invented from extensions,
        # whose namespace contents carry no defined semantics.
        name=name if isinstance(name, str) and name else plugin_dir.name,
        path=plugin_dir,
        description=str(meta.get("description", "") or ""),
        version=str(v) if (v := meta.get("version")) is not None else "",
        author=author_val if isinstance(author_val, dict) else None,
        keywords=_string_list(meta.get("keywords")),
        homepage=_safe_url(meta.get("homepage")),
        repository=_safe_url(meta.get("repository")),
        license=str(meta.get("license", "") or ""),
        **_owned_components(context, node, plugin_resolved),
        has_readme=safe_is_file(plugin_dir / "README.md"),
    )


def _read_json_dict(node: LintTarget) -> dict:
    data, error = read_json(node.path)
    return data if not error and isinstance(data, dict) else {}


def _interface_field(meta: dict, key: str) -> str:
    """Codex keeps presentation fields under ``interface``."""
    interface = meta.get("interface")
    if isinstance(interface, dict):
        return str(interface.get(key, "") or "")
    return ""


# Schemes a generated documentation link may use. Anything else — most
# pointedly ``javascript:`` — is dropped: HTML-escaping an href stops
# attribute breakout but does nothing about the scheme, so a manifest that
# a marketplace merely *accepted* could run script in the docs origin when
# a reader clicks through.
_SAFE_URL_SCHEMES = {"http", "https", "mailto"}


# A URL that carries one of these is not a URL. Scheme validation stops
# ``javascript:``; it says nothing about a quote inside an otherwise
# allowed ``https:`` value, which closes the ``href`` attribute it is
# written into and opens an event handler after it. The renderers escape
# for attribute context, and rejecting here means a value that ever
# reaches a sink through some other path is already not weaponisable.
_URL_FORBIDDEN = set("\"'<>`") | {chr(c) for c in range(0x21)} | {chr(0x7F)}


def _safe_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    candidate = value.strip()
    # CommonMark decodes character references in link destinations, so
    # ``javascript&colon;alert(1)`` carries no literal colon here yet
    # renders as a script-executing link. Validate and emit the decoded
    # form; the loop is bounded so ``&amp;colon;``-style nesting cannot
    # smuggle a scheme past a single decode either.
    for _ in range(5):
        decoded = html.unescape(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    else:
        return ""
    if candidate.startswith("//"):
        return ""
    if _URL_FORBIDDEN & set(candidate):
        return ""
    scheme, sep, _ = candidate.partition(":")
    try:
        authority = urlsplit(candidate).netloc
    except ValueError:
        return ""
    if "@" in authority:
        return ""
    if (
        sep
        and scheme.lower() in {"http", "https"}
        and (not candidate[len(scheme) + 1 :].startswith("//") or not authority)
    ):
        return ""
    # Parentheses survive the character filter but delimit the Markdown
    # sink: ``https://safe.example/)![x](https://evil/pixel`` closes the
    # ``[Homepage](...)`` link early and injects a remote image into the
    # generated page. Percent-encode them — equivalent per RFC 3986, inert
    # in Markdown, and already-escaped attribute context is unaffected.
    candidate = candidate.replace("(", "%28").replace(")", "%29")
    if not sep:
        return candidate  # relative or bare host — no scheme to abuse
    return candidate if scheme.lower() in _SAFE_URL_SCHEMES else ""


def _string_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v]


def _extract_owned_skills(context: RepositoryContext, plugin_resolved: Path) -> List[SkillDoc]:
    """Skills the tree assigned to this plugin.

    The build tagged each ``SkillNode`` with its owning plugin root, so
    membership is a read, not a path match.
    """
    docs = []
    for skill_node in context.lint_tree.find(SkillNode):
        if skill_node.plugin_owner != plugin_resolved:
            continue
        doc = _extract_skill(skill_node)
        if doc:
            docs.append(doc)
    return sorted(docs, key=lambda d: name_str(d.name))


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
        homepage=_safe_url(meta.get("homepage")),
        repository=_safe_url(meta.get("repository")),
        license=str(meta.get("license", "")) or "",
        commands=_extract_commands(plugin_node),
        skills=_extract_skills(plugin_node),
        agents=_extract_agents(plugin_node),
        hooks=_extract_hooks(plugin_node.find(HooksBlock)),
        mcp_servers=_extract_mcp_servers(plugin_node.find(McpBlock), meta),
        rules=_extract_rules(plugin_node),
        has_readme=bool(plugin_node.find(ReadmeBlock)),
    )


# -- Commands --


def _extract_commands(plugin_node: PluginNode) -> List[CommandDoc]:
    return _command_docs(plugin_node.find(CommandBlock))


def _command_docs(blocks) -> List[CommandDoc]:
    docs = []
    for block in blocks:
        name_lines = block.section("Name").strip().splitlines()
        full_name = name_lines[0] if name_lines else ""
        synopsis = _strip_fences(block.section("Synopsis"))
        body_text = block.section("Description")
        docs.append(
            CommandDoc(
                name=block.path.stem,
                file_path=block.path,
                description=_scalar_str(block.field_value("description", "")),
                full_name=full_name,
                synopsis=synopsis,
                body=body_text,
            )
        )
    return sorted(docs, key=lambda d: name_str(d.name))


# -- Skills --


def _extract_skills(plugin_node: PluginNode) -> List[SkillDoc]:
    docs = []
    for skill_node in plugin_node.find(SkillNode):
        doc = _extract_skill(skill_node)
        if doc:
            docs.append(doc)
    return sorted(docs, key=lambda d: name_str(d.name))


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
    # Both renderers ", ".join() this, so one non-string element raises
    # TypeError and takes documentation for the whole catalog with it.
    # agentskill-valid reports the malformed entry; the docs just skip it.
    allowed_tools = [t for t in allowed_tools if isinstance(t, str)]
    description = block.field_value("description", "")
    if not isinstance(description, str):
        # Invalid frontmatter is reported by agentskill-valid, but docs
        # generation must remain total: Markdown joins this value as text
        # and the HTML search index lowercases it.
        description = ""

    return SkillDoc(
        # Normalized here, not only in sort keys: the value is serialized
        # into the page data, and the search box lowercases it.
        name=name_str(block.field_value("name", skill_node.path.name)),
        dir_path=skill_node.path,
        description=description,
        license=block.field_value("license", ""),
        compatibility=block.field_value("compatibility", ""),
        metadata=block.field_value("metadata", {}),
        allowed_tools=allowed_tools or [],
        body=block.body_text.strip(),
    )


# -- Agents --


def _extract_agents(plugin_node: PluginNode) -> List[AgentDoc]:
    return _agent_docs(plugin_node.find(AgentBlock))


def _agent_docs(blocks) -> List[AgentDoc]:
    docs = []
    for block in blocks:
        docs.append(
            AgentDoc(
                name=_scalar_str(block.field_value("name", "")) or block.path.stem,
                file_path=block.path,
                description=_scalar_str(block.field_value("description", "")),
                body=block.body_text.strip(),
            )
        )
    return sorted(docs, key=lambda d: name_str(d.name))


# -- Hooks --


def _extract_hooks(blocks: List[HooksBlock]) -> List[HookDoc]:
    docs = []
    for block in blocks:
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


def _extract_mcp_servers(blocks: List[McpBlock], plugin_meta: dict) -> List[McpServerDoc]:
    servers: List[McpServerDoc] = []
    seen: set = set()

    for block in blocks:
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
    return _rule_docs(plugin_node.find(PluginRuleBlock))


def _rule_docs(blocks) -> List[RuleFileDoc]:
    docs = []
    for block in blocks:
        globs: List[str] = []
        paths = block.field_value("paths", [])
        if isinstance(paths, list):
            globs = [str(p) for p in paths]
        docs.append(
            RuleFileDoc(
                name=block.path.stem,
                file_path=block.path,
                description=_scalar_str(block.field_value("description", "")),
                globs=globs,
                body=block.body_text.strip(),
            )
        )
    return sorted(docs, key=lambda d: name_str(d.name))


# -- Helpers --


def _scalar_str(value: Any) -> str:
    """A frontmatter value the renderers may join as text, or ``""``.

    Same totality contract as skill descriptions above: the frontmatter
    rules report the malformed value; docs generation must not crash on
    a list- or dict-valued field reaching ``"\\n".join()``.
    """
    return value if isinstance(value, str) else ""


def _strip_fences(text: str) -> str:
    """Remove leading/trailing code fences from a block."""
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return text.strip()
