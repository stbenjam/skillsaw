"""Frontmattered files: YAML frontmatter followed by a markdown body.

:class:`FrontmatteredBlock` is a container (not itself a ``ContentBlock``):
the lintable prose lives in a :class:`BodyContent` child and each frontmatter
key is exposed as a :class:`FrontmatterField` child.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

import yaml

from skillsaw.lint_target import LintTarget
from skillsaw.utils import (
    _FRONTMATTER_RE,
    read_text,
    parse_frontmatter,
    extract_section,
    frontmatter_key_line as _frontmatter_key_line,
    _extract_frontmatter_text,
    yaml_line_map as _yaml_line_map,
)

from .base import ContentBlock


def _parse_file_frontmatter(
    path: Path,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
    """Parse YAML frontmatter from a markdown file.

    Returns (frontmatter_dict, error_string, error_line, body_after_frontmatter,
    fm_line_count).  ``fm_line_count`` is the number of file lines occupied by
    the frontmatter block (including the ``---`` delimiters).
    """
    content = read_text(path)
    if content is None:
        return None, f"Failed to read file: {path}", None, "", 0
    if not content.startswith("---"):
        return None, None, None, content, 0
    fm, body, error_line = parse_frontmatter(content)
    if fm is None:
        return (
            None,
            "Invalid frontmatter (malformed YAML or missing closing ---)",
            error_line,
            body,
            0,
        )
    fm_line_count = content[: len(content) - len(body)].count("\n")
    return fm, None, None, body, fm_line_count


@dataclass(eq=False)
class FrontmatterField(LintTarget):
    """A single key-value pair from YAML frontmatter, exposed as a tree node."""

    name: str = ""
    value: Any = None
    field_line: Optional[int] = None

    def __eq__(self, other):
        if not isinstance(other, FrontmatterField):
            return NotImplemented
        return (
            type(self) is type(other)
            and self.path.resolve() == other.path.resolve()
            and self.name == other.name
        )

    def __hash__(self):
        return hash((type(self), self.path.resolve(), self.name))

    def tree_label(self) -> str:
        return f"frontmatter:{self.name}"

    def estimate_tokens(self) -> int:
        if self.value is None:
            return 0
        return len(str(self.value)) // 4


@dataclass(eq=False)
class BodyContent(ContentBlock):
    """The lintable markdown body of a frontmattered file."""

    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]:
        if not self.body:
            return None
        if strip_code_blocks:
            return self._stripped_body()
        return self.body

    def write_body(self, new_body: str) -> None:
        content = read_text(self.path)
        if content is None or not content.startswith("---"):
            self.path.write_text(new_body, encoding="utf-8")
        else:
            fm, file_body, _ = parse_frontmatter(content)
            if fm is None:
                raise ValueError("Cannot rewrite body: frontmatter is malformed")
            fm_section = content[: len(content) - len(file_body)]
            self.path.write_text(fm_section + new_body, encoding="utf-8")
        self.body = new_body

    def tree_label(self) -> str:
        return "body"


@dataclass(eq=False)
class FrontmatteredBlock(LintTarget):
    """Container for files with YAML frontmatter followed by a markdown body.

    Not a ``ContentBlock`` itself — the lintable content lives in the
    ``BodyContent`` child node.  Frontmatter keys are exposed as
    ``FrontmatterField`` children.
    """

    category: str = ""
    content_lintable_fields: Tuple[str, ...] = ()

    def file_line(self, line: int) -> int:
        """For FrontmatteredBlock, line numbers are already file-absolute."""
        return line

    _fm_parsed: Optional[
        Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]
    ] = field(default=None, init=False, repr=False)

    def __eq__(self, other):
        if not isinstance(other, FrontmatteredBlock):
            return NotImplemented
        return type(self) is type(other) and self.resolved_path == other.resolved_path

    def __hash__(self):
        return hash((type(self), self.resolved_path))

    def walk(self) -> Iterator["LintTarget"]:
        self._ensure_parsed()
        yield from super().walk()

    def _ensure_parsed(self) -> None:
        if self._fm_parsed is None:
            self._fm_parsed = _parse_file_frontmatter(self.path)
            self._build_children()

    def _build_children(self) -> None:
        # Children change: stale find() memos on this node and its ancestors
        # must not survive (e.g. after write_frontmatter_text resets _fm_parsed).
        self.invalidate_find_cache()
        self.children = [
            c for c in self.children if not isinstance(c, (FrontmatterField, BodyContent))
        ]
        fm = self._fm_parsed[0]
        if fm:
            for key, value in fm.items():
                self.children.append(
                    FrontmatterField(
                        path=self.path,
                        name=key,
                        value=value,
                        field_line=self.key_line(key),
                        parent=self,
                    )
                )
        body_text = self._fm_parsed[3]
        if body_text:
            self.children.append(
                BodyContent(
                    path=self.path,
                    category=self.category,
                    line_offset=self._fm_parsed[4],
                    body=body_text,
                    parent=self,
                )
            )

    def field(self, name: str) -> Optional[FrontmatterField]:
        """Return the ``FrontmatterField`` child with the given key name, or ``None``."""
        for fld in self.find(FrontmatterField):
            if fld.name == name:
                return fld
        return None

    def field_value(self, name: str, default: Any = None) -> Any:
        """Return the value of the named frontmatter field, or *default*."""
        fld = self.field(name)
        return fld.value if fld is not None else default

    @property
    def has_frontmatter(self) -> bool:
        self._ensure_parsed()
        return self._fm_parsed[0] is not None

    @property
    def frontmatter_error(self) -> Optional[str]:
        self._ensure_parsed()
        return self._fm_parsed[1]

    @property
    def frontmatter_error_line(self) -> Optional[int]:
        self._ensure_parsed()
        return self._fm_parsed[2]

    @property
    def body_text(self) -> str:
        self._ensure_parsed()
        return self._fm_parsed[3]

    def key_line(self, key: str) -> Optional[int]:
        return _frontmatter_key_line(self.path, key)

    def line_map(self) -> Dict[str, int]:
        content = read_text(self.path)
        if content is None:
            return {}
        fm_text, offset = _extract_frontmatter_text(content)
        if fm_text is None:
            return {}
        return _yaml_line_map(fm_text, line_offset=offset)

    def estimate_tokens(self) -> int:
        self._ensure_parsed()
        return super().estimate_tokens()

    def tree_label(self) -> str:
        return f"{self.path.name} ({self.category})"

    def read_frontmatter_text(self) -> str:
        """Return the raw YAML text between the --- delimiters (no delimiters)."""
        content = read_text(self.path)
        if not content or not content.startswith("---"):
            return ""
        fm_text, _ = _extract_frontmatter_text(content)
        return fm_text or ""

    def write_frontmatter_text(self, new_fm_text: str) -> None:
        """Replace just the frontmatter YAML, preserving the body.

        Raises ValueError if new_fm_text is not valid YAML.
        """
        try:
            data = yaml.safe_load(new_fm_text)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("Frontmatter must be a YAML mapping")

        fm = new_fm_text.rstrip("\n") + "\n"

        content = read_text(self.path)
        if not content:
            self.path.write_text(f"---\n{fm}---\n", encoding="utf-8")
            self._fm_parsed = None
            self.invalidate_find_cache()
            return

        m = _FRONTMATTER_RE.match(content)
        if m:
            body_after = content[m.end() :]
            self.path.write_text(f"---\n{fm}---\n{body_after}", encoding="utf-8")
        elif content.startswith("---"):
            lines = content.split("\n")
            close_idx = None
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "---":
                    close_idx = i
                    break
            if close_idx is not None:
                body_after = "\n".join(lines[close_idx + 1 :])
                if body_after and not body_after.startswith("\n"):
                    body_after = "\n" + body_after
                self.path.write_text(f"---\n{fm}---{body_after}", encoding="utf-8")
            else:
                body_after = "\n".join(lines[1:])
                self.path.write_text(f"---\n{fm}---\n{body_after}", encoding="utf-8")
        else:
            self.path.write_text(f"---\n{fm}---\n{content}", encoding="utf-8")
        self._fm_parsed = None
        # Children will be rebuilt on the next walk — cached find() results
        # on this node and its ancestors must not serve the old fields.
        self.invalidate_find_cache()


ParsedFrontmatterBlock = FrontmatteredBlock


@dataclass(eq=False)
class CursorRuleBlock(FrontmatteredBlock):
    """.cursor/rules/*.mdc files."""

    category: str = "instruction"


@dataclass(eq=False)
class CommandBlock(FrontmatteredBlock):
    """commands/*.md in plugins."""

    category: str = "command"

    def section(self, heading: str, level: int = 2) -> str:
        content = read_text(self.path)
        if content is None:
            return ""
        return extract_section(content, heading, level)


@dataclass(eq=False)
class AgentBlock(FrontmatteredBlock):
    """agents/*.md in plugins or APM agent files."""

    category: str = "agent"


@dataclass(eq=False)
class SkillBlock(FrontmatteredBlock):
    """SKILL.md in skills."""

    category: str = "skill"


@dataclass(eq=False)
class PluginRuleBlock(FrontmatteredBlock):
    """rules/*.md in plugins."""

    category: str = "rule"
