"""Data models for extracted documentation content."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from skillsaw.context import RepositoryType


@dataclass
class CommandDoc:
    name: str
    file_path: Path
    description: str = ""
    full_name: str = ""
    synopsis: str = ""
    body: str = ""


@dataclass
class SkillDoc:
    name: str
    dir_path: Path
    description: str = ""
    license: str = ""
    compatibility: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    allowed_tools: List[str] = field(default_factory=list)
    body: str = ""


@dataclass
class AgentDoc:
    name: str
    file_path: Path
    description: str = ""
    body: str = ""


@dataclass
class HookEntry:
    matcher: str
    hooks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class HookDoc:
    event_type: str
    entries: List[HookEntry] = field(default_factory=list)


@dataclass
class McpServerDoc:
    name: str
    server_type: str
    config: Dict[str, Any] = field(default_factory=dict)
    source_file: str = ""


@dataclass
class RuleFileDoc:
    name: str
    file_path: Path
    description: str = ""
    globs: List[str] = field(default_factory=list)
    body: str = ""


@dataclass
class PluginDoc:
    name: str
    path: Path
    description: str = ""
    version: str = ""
    author: Optional[Dict[str, Any]] = None
    commands: List[CommandDoc] = field(default_factory=list)
    skills: List[SkillDoc] = field(default_factory=list)
    agents: List[AgentDoc] = field(default_factory=list)
    hooks: List[HookDoc] = field(default_factory=list)
    mcp_servers: List[McpServerDoc] = field(default_factory=list)
    rules: List[RuleFileDoc] = field(default_factory=list)
    has_readme: bool = False


@dataclass
class MarketplaceDoc:
    name: str
    owner: Optional[Dict[str, Any]] = None
    plugins: List[PluginDoc] = field(default_factory=list)


@dataclass
class DocsOutput:
    repo_type: RepositoryType
    title: str
    marketplace: Optional[MarketplaceDoc] = None
    plugins: List[PluginDoc] = field(default_factory=list)
    skills: List[SkillDoc] = field(default_factory=list)
