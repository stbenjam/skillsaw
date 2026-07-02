"""Structured JSON configuration blocks: hooks, MCP, and settings.

These deliberately subclass :class:`LintTarget` (not ``ContentBlock``): they
are machine configuration, not prose for an agent's context window, so
content-quality rules never see them.  Dedicated rules locate them with
``find(HooksBlock)`` etc. and read ``raw_data``/``parse_error``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_text, read_json


@dataclass
class HookHandler:
    """A single hook handler entry."""

    type: str
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, Any]] = None
    server: Optional[str] = None
    tool: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    timeout: Optional[float] = None
    async_: Optional[bool] = None
    async_rewake: Optional[bool] = None
    once: Optional[bool] = None
    if_: Optional[str] = None
    status_message: Optional[str] = None
    shell: Optional[str] = None
    allowed_env_vars: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HookHandler":
        return cls(
            type=d.get("type", ""),
            command=d.get("command"),
            args=d.get("args"),
            url=d.get("url"),
            headers=d.get("headers"),
            server=d.get("server"),
            tool=d.get("tool"),
            input=d.get("input"),
            prompt=d.get("prompt"),
            model=d.get("model"),
            timeout=d.get("timeout"),
            async_=d.get("async"),
            async_rewake=d.get("asyncRewake"),
            once=d.get("once"),
            if_=d.get("if"),
            status_message=d.get("statusMessage"),
            shell=d.get("shell"),
            allowed_env_vars=d.get("allowedEnvVars"),
        )


@dataclass
class HookEventConfig:
    """A single event config entry (matcher + handlers)."""

    matcher: str = ".*"
    handlers: List[HookHandler] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HookEventConfig":
        handlers: List[HookHandler] = []
        raw_hooks = d.get("hooks", [])
        if isinstance(raw_hooks, list):
            for h in raw_hooks:
                if isinstance(h, dict):
                    handlers.append(HookHandler.from_dict(h))
        return cls(
            matcher=d.get("matcher", ".*"),
            handlers=handlers,
        )


def _parse_json_file(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    data, error = read_json(path)
    return data, error


@dataclass(eq=False)
class JsonConfigBlock(LintTarget):
    """Structured JSON configuration in the lint tree.

    Deliberately not a :class:`ContentBlock`: these files are machine
    configuration, not prose for an agent's context window, so
    content-quality rules never see them. Dedicated rules locate them
    with ``find(HooksBlock)`` etc. and read ``raw_data``/``parse_error``.
    """

    category: str = ""
    _parsed: Optional[Tuple[Optional[Any], Optional[str]]] = field(
        default=None, init=False, repr=False
    )

    def _ensure_parsed(self) -> None:
        if self._parsed is None:
            self._parsed = _parse_json_file(self.path)

    @property
    def parse_error(self) -> Optional[str]:
        self._ensure_parsed()
        return self._parsed[1]

    @property
    def raw_data(self) -> Optional[Dict[str, Any]]:
        self._ensure_parsed()
        data = self._parsed[0]
        return data if isinstance(data, dict) else None

    def estimate_tokens(self) -> int:
        content = read_text(self.path)
        return len(content) // 4 if content else 0

    def tree_label(self) -> str:
        return f"{self.path.name} ({self.category})"


@dataclass(eq=False)
class HooksBlock(JsonConfigBlock):
    """hooks/hooks.json in a plugin."""

    category: str = "hooks"

    @property
    def events(self) -> Dict[str, List[HookEventConfig]]:
        data = self.raw_data
        if data is None:
            return {}
        hooks_obj = data.get("hooks", {})
        if not isinstance(hooks_obj, dict):
            return {}
        result: Dict[str, List[HookEventConfig]] = {}
        for event_type, configs in hooks_obj.items():
            if not isinstance(configs, list):
                continue
            entries: List[HookEventConfig] = []
            for cfg in configs:
                if isinstance(cfg, dict):
                    entries.append(HookEventConfig.from_dict(cfg))
            if entries:
                result[event_type] = entries
        return result


@dataclass
class McpServerConfig:
    """A single MCP server configuration."""

    name: str
    type: str = "stdio"
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, Any]] = None
    headers_helper: Optional[str] = None
    startup_timeout: Optional[float] = None
    timeout: Optional[float] = None
    always_load: Optional[bool] = None
    oauth: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, name: str, d: Dict[str, Any]) -> "McpServerConfig":
        return cls(
            name=name,
            type=d.get("type", "stdio"),
            command=d.get("command"),
            args=d.get("args"),
            env=d.get("env"),
            cwd=d.get("cwd"),
            url=d.get("url"),
            headers=d.get("headers"),
            headers_helper=d.get("headersHelper"),
            startup_timeout=d.get("startupTimeout"),
            timeout=d.get("timeout"),
            always_load=d.get("alwaysLoad"),
            oauth=d.get("oauth"),
        )


@dataclass(eq=False)
class McpBlock(JsonConfigBlock):
    """.mcp.json at the project root or inside a plugin."""

    category: str = "mcp"

    @property
    def servers(self) -> List[McpServerConfig]:
        data = self.raw_data
        if data is None:
            return []
        servers_dict = data.get("mcpServers", data)
        if not isinstance(servers_dict, dict):
            return []
        return [
            McpServerConfig.from_dict(name, cfg)
            for name, cfg in servers_dict.items()
            if isinstance(cfg, dict)
        ]

    @property
    def server_names(self) -> Set[str]:
        return {s.name for s in self.servers}


@dataclass(eq=False)
class SettingsBlock(JsonConfigBlock):
    """settings.json or settings.local.json in .claude/."""

    category: str = "settings"

    @property
    def hooks_events(self) -> Dict[str, List[HookEventConfig]]:
        """Extract hooks, supporting both nested and flat formats.

        Nested (hooks.json style): { matcher, hooks: [{type, command}] }
        Flat (settings.json style): { type, command, matcher? }
        """
        data = self.raw_data
        if data is None:
            return {}
        hooks_obj = data.get("hooks", {})
        if not isinstance(hooks_obj, dict):
            return {}
        result: Dict[str, List[HookEventConfig]] = {}
        for event_type, configs in hooks_obj.items():
            if not isinstance(configs, list):
                continue
            entries: List[HookEventConfig] = []
            for cfg in configs:
                if not isinstance(cfg, dict):
                    continue
                if "hooks" in cfg:
                    entries.append(HookEventConfig.from_dict(cfg))
                elif "type" in cfg:
                    handler = HookHandler.from_dict(cfg)
                    matcher = cfg.get("matcher", ".*")
                    entries.append(HookEventConfig(matcher=matcher, handlers=[handler]))
            if entries:
                result[event_type] = entries
        return result
