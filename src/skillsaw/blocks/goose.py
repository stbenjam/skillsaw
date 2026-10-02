"""Structured Goose recipes and their extracted instruction prose."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from ruamel.yaml.scalarstring import LiteralScalarString

from skillsaw.formats.goose import recipe_string
from skillsaw.lint_target import LintTarget
from skillsaw.utils import commented_item_line, commented_key_line, read_yaml_commented

from .base import ContentBlock
from .json_config import McpConfigRole, McpShapeDeferral


@dataclass(eq=False)
class GooseRecipeBlock(LintTarget, McpConfigRole):
    """A recipe document, with external extensions exposed to MCP policy."""

    workspace: Path = Path(".")
    shape_deferral: ClassVar[McpShapeDeferral] = McpShapeDeferral(
        syntax_error_rule="goose-recipe-valid"
    )
    surface_rule: ClassVar[str] = "goose-recipe-valid"
    credential_maps: ClassVar[tuple] = (("envs", False), ("headers", True))
    connection_url_keys: ClassVar[tuple] = ("uri",)
    syntax_name: ClassVar[str] = "Goose recipe"
    _parsed: tuple | None = field(default=None, init=False, repr=False)

    def _ensure_parsed(self) -> tuple:
        if self._parsed is None:
            self._parsed = read_yaml_commented(self.path)
        return self._parsed

    @property
    def raw_data(self):
        data = self._ensure_parsed()[0]
        return data.get("recipe") if isinstance(data, dict) and "recipe" in data else data

    @property
    def parse_error(self):
        # Parser exceptions can include untrusted source containing secrets.
        return "Cannot parse recipe document" if self._ensure_parsed()[1] else None

    @property
    def error_line(self):
        return None if self.path.suffix == ".json" else self._ensure_parsed()[2]

    def key_line(self, mapping, key):
        return None if self.path.suffix == ".json" else commented_key_line(mapping, key)

    def source_line_for(self, mapping, key):
        return self.key_line(mapping, key)

    @property
    def source_line(self):
        return self.key_line(self.raw_data, "extensions")

    def server_entries(self):
        data = self.raw_data
        extensions = data.get("extensions") if isinstance(data, dict) else None
        if not isinstance(extensions, list):
            return []
        return [
            (recipe_string(ext.get("name")) or f"extensions[{index}]", ext)
            for index, ext in enumerate(extensions)
            if isinstance(ext, dict)
            and isinstance(ext.get("type"), str)
            and ext["type"] in {"stdio", "streamable_http"}
        ]

    def _server_config(self, name, cfg):
        from .json_config import McpServerConfig

        return McpServerConfig.from_dict(
            name, {**cfg, "command": cfg.get("cmd"), "url": cfg.get("uri"), "env": cfg.get("envs")}
        )

    def tree_label(self):
        return f"{self.path.name} [goose recipe]"

    def prose_blocks(self):
        """Extract prompts without passing settings or extension commands to prose rules."""
        data = self.raw_data
        if not isinstance(data, dict):
            return []
        values = [
            (key, data.get(key), self.key_line(data, key)) for key in ("instructions", "prompt")
        ]
        activities = data.get("activities")
        if isinstance(activities, list):
            values.extend(
                (
                    f"activities[{index}]",
                    value,
                    None if self.path.suffix == ".json" else commented_item_line(activities, index),
                )
                for index, value in enumerate(activities)
            )
        blocks = []
        for key, value, line in values:
            body = recipe_string(value)
            if not body:
                continue
            # Literal scalars preserve source lines. Folded and quoted scalars
            # can collapse physical lines, so every body line maps to the key.
            literal = isinstance(value, LiteralScalarString)
            line_map = (
                (lambda body_line, start=line: start + body_line)
                if literal and line is not None
                else (lambda body_line, start=line: start or 0)
            )
            blocks.append(
                GooseRecipeProseBlock(path=self.path, body=body, field_name=key, _line_map=line_map)
            )
        return blocks


@dataclass(eq=False)
class GooseRecipeProseBlock(ContentBlock):
    """Decoded recipe prose; fixes cannot safely splice arbitrary YAML strings."""

    category: str = "goose-prompt"
    field_name: str = ""
    diagnostic_only: ClassVar[bool] = True

    def read_body(self, *, strip_code_blocks=True):
        return self._stripped_body() if strip_code_blocks else self.body or ""

    def write_body(self, new_body):
        raise NotImplementedError("Goose recipe prose is diagnostic-only")

    def tree_label(self):
        return f"{self.field_name} ({self.category})"

    def fingerprint_identity(self, body_line):
        lines = (self.body or "").split("\n")
        content = lines[body_line - 1].strip() if body_line and 1 <= body_line <= len(lines) else ""
        return f"{len(self.field_name)}:{self.field_name}\0{content}"

    def __eq__(self, other):
        if not isinstance(other, GooseRecipeProseBlock):
            return NotImplemented
        return self.resolved_path == other.resolved_path and self.field_name == other.field_name

    def __hash__(self):
        return hash((type(self), self.resolved_path, self.field_name))
