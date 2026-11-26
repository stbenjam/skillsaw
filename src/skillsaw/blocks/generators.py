"""Generator sources are instructions; their configuration is not prose."""

from dataclasses import dataclass, field
from typing import ClassVar, Optional

from skillsaw.formats.generators import parse_rulesync_frontmatter
from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_toml

from .base import ContentBlock, FileContentBlock
from .frontmatter import FrontmatterField, FrontmatteredBlock
from .json_config import JsonConfigBlock


def is_generator_source(node):
    """Whether a node is part of an authored generator parser view."""
    while node is not None:
        if isinstance(node, (RulerRuleBlock, RulesyncRuleBlock)):
            return True
        node = node.parent
    return False


@dataclass(eq=False)
class RulerRuleBlock(FileContentBlock):
    """Ruler concatenates rule Markdown verbatim, including apparent frontmatter."""

    category: str = "instruction"


@dataclass(eq=False)
class RulesyncDescriptionBlock(FrontmatterField, ContentBlock):
    """Decoded description prose, anchored to its YAML field and never rewritten."""

    category: str = "generator-description"
    diagnostic_only: ClassVar[bool] = True

    def read_body(self, *, strip_code_blocks=True):
        return self._stripped_body() if strip_code_blocks else self.value

    def write_body(self, new_body):
        raise NotImplementedError("Decoded frontmatter descriptions are diagnostic-only")

    def file_line(self, body_line):
        return self.field_line


@dataclass(eq=False)
class RulesyncRuleBlock(FrontmatteredBlock):
    """The body and description are authored instructions, targets/globs are data."""

    category: str = "instruction"
    _rulesync_key_lines: dict = field(default_factory=dict, init=False, repr=False)
    _portable_keys: bool = field(default=True, init=False, repr=False)

    def _build_children(self):
        super()._build_children()
        self.children = [
            (
                RulesyncDescriptionBlock(
                    path=child.path,
                    parent=self,
                    name=child.name,
                    value=child.value,
                    field_line=child.field_line,
                    _line_map=lambda _line, start=child.field_line: start or 0,
                )
                if isinstance(child, FrontmatterField)
                and child.name == "description"
                and isinstance(child.value, str)
                else child
            )
            for child in self.children
        ]

    @property
    def raw_data(self):
        self._ensure_parsed()
        return self._fm_parsed[0]

    def _parse_frontmatter_content(self, content):
        parsed = parse_rulesync_frontmatter(content)
        self._rulesync_key_lines = parsed.key_lines
        self._portable_keys = parsed.portable_keys
        return parsed[:5]

    @property
    def portable_keys(self):
        """Whether key normalization is within the copy recognizer's subset."""
        self._ensure_parsed()
        return self._portable_keys

    def key_line(self, key):
        self._ensure_parsed()
        return self._rulesync_key_lines.get(key)

    def line_map(self):
        self._ensure_parsed()
        return dict(self._rulesync_key_lines)


@dataclass(eq=False)
class RulerConfigBlock(LintTarget):
    _parsed: Optional[tuple] = field(default=None, init=False, repr=False)

    def _ensure_parsed(self):
        if self._parsed is None:
            self._parsed = read_toml(self.path)

    @property
    def raw_data(self):
        self._ensure_parsed()
        return self._parsed[0]

    @property
    def parse_error(self):
        self._ensure_parsed()
        return self._parsed[1]

    def tree_label(self):
        return f"{self.path.name} (ruler config)"


@dataclass(eq=False)
class RulesyncConfigBlock(JsonConfigBlock):
    category: str = "rulesync config"
    jsonc: ClassVar[bool] = True
    # jsonc-parser, used by the released config loader, keeps the last key.
    duplicate_keys_fatal: ClassVar[bool] = False
