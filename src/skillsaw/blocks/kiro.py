"""Kiro agent configuration, steering prose, and embedded MCP roles."""

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Mapping, Optional, Tuple

from skillsaw.formats.kiro import MCP_CREDENTIAL_KEY_ALIASES
from skillsaw.lint_target import LintTarget
from skillsaw.utils import commented_key_line, read_frontmatter_commented

from .base import ContentBlock, FileContentBlock
from .frontmatter import FrontmatteredBlock, FrontmatterField
from .json_config import JsonConfigBlock, McpBlock, McpConfigRole, McpShapeDeferral


@dataclass(eq=False)
class KiroSteeringBlock(FrontmatteredBlock):
    """Recursive workspace steering, with metadata separate from prose."""

    category: str = "instruction"

    @property
    def hooks_events(self):
        # Kiro hooks do not use the inherited Claude frontmatter contract.
        return {}


@dataclass(eq=False)
class KiroPromptFileBlock(FileContentBlock):
    """A contained file explicitly used as an agent's system prompt."""

    category: str = "agent"


@dataclass(eq=False)
class KiroInlinePromptBlock(ContentBlock):
    """Decoded JSON prompt text; never rewrite a synthetic source span."""

    # The whole-file context budget would charge the JSON config as prose.
    # As with promptfoo-prompt and hook-prompt, leave that budget out.
    category: str = "agent-prompt"
    diagnostic_only: ClassVar[bool] = True

    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]:
        return self._stripped_body() if strip_code_blocks else self.body

    def write_body(self, new_body: str) -> None:
        raise NotImplementedError("Embedded Kiro prompts are diagnostic-only")

    def file_line(self, body_line: int) -> int:
        return 0

    def fingerprint_identity(self, body_line: Optional[int]) -> str:
        content = self.markdown.line(body_line or 0).strip()
        return f"6:prompt\0{content}"


class KiroAgentConfigRole:
    """Agent metadata interface shared by JSON and frontmatter containers."""


@dataclass(eq=False)
class KiroJsonAgentBlock(JsonConfigBlock, KiroAgentConfigRole):
    """CLI 2.x / V3 JSON agent configuration, not instruction prose."""

    category: str = "agent"
    strict_json: ClassVar[bool] = True
    duplicate_keys_fatal: ClassVar[bool] = False
    _children_built: bool = field(default=False, init=False, repr=False)

    def _before_walk(self) -> None:
        if self._children_built:
            return
        self._children_built = True
        data = self.raw_data
        if data is None:
            return
        prompt = data.get("prompt")
        inline_prompt = isinstance(prompt, str) and not prompt.startswith("file://")
        self.children.extend(
            FrontmatterField(path=self.path, name=key, value=value, parent=self)
            for key, value in data.items()
            if key != "prompt" or not inline_prompt
        )
        if inline_prompt:
            self.children.append(KiroInlinePromptBlock(path=self.path, body=prompt, parent=self))
        _attach_mcp(self, data)

    @property
    def frontmatter_error(self) -> Optional[str]:
        return self.parse_error

    @property
    def has_frontmatter(self) -> bool:
        return self.raw_data is not None

    def field(self, name: str) -> Optional[FrontmatterField]:
        self._before_walk()
        return next(
            (c for c in self.children if isinstance(c, FrontmatterField) and c.name == name), None
        )

    def field_value(self, name: str, default: Any = None) -> Any:
        return (self.raw_data or {}).get(name, default)

    def key_line(self, key: str) -> Optional[int]:
        return None


@dataclass(eq=False)
class KiroMarkdownAgentBlock(FrontmatteredBlock, KiroAgentConfigRole):
    """IDE 1.x / CLI V3 Markdown: YAML metadata and a system-prompt body."""

    category: str = "agent"

    @property
    def hooks_events(self):
        return {}

    def _parse_frontmatter_file(self):
        parsed = super()._parse_frontmatter_file()
        if parsed[0] is None:
            return parsed
        data, error, line = read_frontmatter_commented(self.path)
        if error or not isinstance(data, dict):
            return None, error or "Agent frontmatter must be a mapping", line, parsed[3], parsed[4]
        return data, None, None, parsed[3], parsed[4]

    @property
    def raw_data(self) -> Optional[Dict[str, Any]]:
        data, error, _line = read_frontmatter_commented(self.path)
        return data if not error and isinstance(data, dict) else None

    def _build_children(self) -> None:
        self.children = [c for c in self.children if not isinstance(c, KiroInlineMcpBlock)]
        super()._build_children()
        _attach_mcp(self, self.raw_data or {})


@dataclass(eq=False)
class KiroMcpBlock(McpBlock):
    """Workspace settings/mcp.json, including partial server overrides."""

    strict_json: ClassVar[bool] = True
    duplicate_keys_fatal: ClassVar[bool] = False
    allow_bare_server_map: ClassVar[bool] = False
    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = McpShapeDeferral(
        syntax_error_rule="kiro-mcp-valid"
    )
    surface_rule: ClassVar[Optional[str]] = "kiro-mcp-valid"
    credential_maps: ClassVar[Tuple[Tuple[str, bool], ...]] = (
        ("env", False),
        ("headers", True),
        ("oauth", False),
    )
    credential_key_aliases: ClassVar[Mapping[str, str]] = MCP_CREDENTIAL_KEY_ALIASES


@dataclass(eq=False)
class KiroInlineMcpBlock(McpConfigRole, LintTarget):
    """Agent MCP payload, with source marks for Markdown frontmatter."""

    category: str = "mcp"
    inline_data: Optional[Dict[str, Any]] = None
    source_line: Optional[int] = None
    yaml_offset: int = 0
    allow_bare_server_map: ClassVar[bool] = False
    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = McpShapeDeferral()
    credential_maps: ClassVar[Tuple[Tuple[str, bool], ...]] = KiroMcpBlock.credential_maps
    credential_key_aliases: ClassVar[Mapping[str, str]] = KiroMcpBlock.credential_key_aliases

    @property
    def raw_data(self) -> Optional[Dict[str, Any]]:
        return self.inline_data

    @property
    def parse_error(self) -> None:
        return None

    def source_line_for(self, node: Any, key: Any) -> Optional[int]:
        line = commented_key_line(node, key)
        return line + self.yaml_offset if line is not None else self.source_line


def _attach_mcp(parent: LintTarget, data: dict) -> None:
    if isinstance(data.get("mcpServers"), dict):
        parent.children.append(
            KiroInlineMcpBlock(
                path=parent.path,
                inline_data={"mcpServers": data["mcpServers"]},
                source_line=parent.key_line("mcpServers"),
                yaml_offset=1 if isinstance(parent, KiroMarkdownAgentBlock) else 0,
                parent=parent,
            )
        )
