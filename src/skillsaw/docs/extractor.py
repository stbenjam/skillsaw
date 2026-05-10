"""Extract structured documentation content from a repository."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from skillsaw.rules.builtin.utils import extract_section, parse_frontmatter


def extract_docs(
    context: RepositoryContext,
    title: Optional[str] = None,
) -> DocsOutput:
    """Extract documentation from a repository context."""
    plugins = [_extract_plugin(context, p) for p in context.plugins]

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
        for skill_path in context.skills:
            if skill_path.resolve() not in plugin_skill_paths:
                doc = _extract_skill(skill_path)
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


def _extract_plugin(context: RepositoryContext, plugin_path: Path) -> PluginDoc:
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
        commands=_extract_commands(plugin_path),
        skills=_extract_skills(plugin_path),
        agents=_extract_agents(plugin_path),
        hooks=_extract_hooks(plugin_path),
        mcp_servers=_extract_mcp_servers(plugin_path, meta),
        rules=_extract_rules(plugin_path),
        has_readme=(plugin_path / "README.md").exists(),
    )


# -- Commands --


def _extract_commands(plugin_path: Path) -> List[CommandDoc]:
    commands_dir = plugin_path / "commands"
    if not commands_dir.is_dir():
        return []
    docs = []
    for cmd_file in sorted(commands_dir.glob("*.md")):
        doc = _parse_command(cmd_file)
        if doc:
            docs.append(doc)
    return docs


def _parse_command(cmd_file: Path) -> Optional[CommandDoc]:
    content = _read(cmd_file)
    if content is None:
        return None
    fm, body = parse_frontmatter(content)
    description = fm.get("description", "") if fm else ""
    name_lines = extract_section(content, "Name").strip().splitlines()
    full_name = name_lines[0] if name_lines else ""
    synopsis = _strip_fences(extract_section(content, "Synopsis"))
    body_text = extract_section(content, "Description")
    return CommandDoc(
        name=cmd_file.stem,
        file_path=cmd_file,
        description=description,
        full_name=full_name,
        synopsis=synopsis,
        body=body_text,
    )


def _strip_fences(text: str) -> str:
    """Remove leading/trailing code fences from a block."""
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


# -- Skills --


def _extract_skills(plugin_path: Path) -> List[SkillDoc]:
    skills_dir = plugin_path / "skills"
    if not skills_dir.is_dir():
        return []
    docs = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        doc = _extract_skill(skill_dir)
        if doc:
            docs.append(doc)
    return docs


def _extract_skill(skill_dir: Path) -> Optional[SkillDoc]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    content = _read(skill_md)
    if content is None:
        return None
    fm, body = parse_frontmatter(content)
    if not fm:
        fm = {}

    allowed_tools = fm.get("allowed-tools", [])
    if isinstance(allowed_tools, str):
        allowed_tools = [allowed_tools]
    if not isinstance(allowed_tools, list):
        allowed_tools = []

    return SkillDoc(
        name=fm.get("name", skill_dir.name),
        dir_path=skill_dir,
        description=fm.get("description", ""),
        license=fm.get("license", ""),
        compatibility=fm.get("compatibility", ""),
        metadata=fm.get("metadata", {}),
        allowed_tools=allowed_tools or [],
        body=body.strip(),
    )


# -- Agents --


def _extract_agents(plugin_path: Path) -> List[AgentDoc]:
    agents_dir = plugin_path / "agents"
    if not agents_dir.is_dir():
        return []
    docs = []
    for agent_file in sorted(agents_dir.glob("*.md")):
        doc = _parse_agent(agent_file)
        if doc:
            docs.append(doc)
    return docs


def _parse_agent(agent_file: Path) -> Optional[AgentDoc]:
    content = _read(agent_file)
    if content is None:
        return None
    fm, body = parse_frontmatter(content)
    if not fm:
        fm = {}
    return AgentDoc(
        name=fm.get("name", agent_file.stem),
        file_path=agent_file,
        description=fm.get("description", ""),
        body=body.strip(),
    )


# -- Hooks --


def _extract_hooks(plugin_path: Path) -> List[HookDoc]:
    hooks_file = plugin_path / "hooks" / "hooks.json"
    if not hooks_file.exists():
        return []
    data = _read_json(hooks_file)
    if not data or not isinstance(data, dict):
        return []
    hooks_obj = data.get("hooks", {})
    if not isinstance(hooks_obj, dict):
        return []

    docs = []
    for event_type in sorted(hooks_obj):
        configs = hooks_obj[event_type]
        if not isinstance(configs, list):
            continue
        entries = []
        for cfg in configs:
            if not isinstance(cfg, dict):
                continue
            entries.append(
                HookEntry(
                    matcher=cfg.get("matcher", ".*"),
                    hooks=cfg.get("hooks", []),
                )
            )
        if entries:
            docs.append(HookDoc(event_type=event_type, entries=entries))
    return docs


# -- MCP Servers --


def _extract_mcp_servers(plugin_path: Path, plugin_meta: Dict[str, Any]) -> List[McpServerDoc]:
    servers: List[McpServerDoc] = []
    seen: set = set()

    mcp_json_path = plugin_path / ".mcp.json"
    if mcp_json_path.exists():
        data = _read_json(mcp_json_path)
        if data and isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
            for name, cfg in data["mcpServers"].items():
                if isinstance(cfg, dict):
                    servers.append(
                        McpServerDoc(
                            name=name,
                            server_type=cfg.get("type", "stdio"),
                            config=cfg,
                            source_file=".mcp.json",
                        )
                    )
                    seen.add(name)

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


# -- Rules (DOT_CLAUDE) --


def _extract_rules(plugin_path: Path) -> List[RuleFileDoc]:
    rules_dir = plugin_path / "rules"
    if not rules_dir.is_dir():
        return []
    docs = []
    for rule_file in sorted(rules_dir.rglob("*.md")):
        doc = _parse_rule_file(rule_file)
        if doc:
            docs.append(doc)
    return docs


def _parse_rule_file(rule_file: Path) -> Optional[RuleFileDoc]:
    content = _read(rule_file)
    if content is None:
        return None
    fm, body = parse_frontmatter(content)
    globs: List[str] = []
    description = ""
    if fm:
        paths = fm.get("paths", [])
        if isinstance(paths, list):
            globs = [str(p) for p in paths]
        description = fm.get("description", "")
    return RuleFileDoc(
        name=rule_file.stem,
        file_path=rule_file,
        description=description,
        globs=globs,
        body=body.strip(),
    )


# -- Helpers --


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError):
        return None


def _read_json(path: Path) -> Optional[Any]:
    content = _read(path)
    if content is None:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None
