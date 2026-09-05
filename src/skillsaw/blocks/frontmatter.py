"""Frontmattered files: YAML frontmatter followed by a markdown body.

:class:`FrontmatteredBlock` is a container (not itself a ``ContentBlock``):
the lintable prose lives in a :class:`BodyContent` child and each frontmatter
key is exposed as a :class:`FrontmatterField` child.
"""

from __future__ import annotations

import json
import re
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from skillsaw.lint_target import LintTarget
from skillsaw.utils import (
    _FRONTMATTER_RE,
    _SAFE_LOADER,
    commented_key_line,
    invalidate_read_caches,
    read_text,
    write_text_preserving,
    parse_frontmatter,
    read_frontmatter_commented,
    extract_section,
    frontmatter_key_line as _frontmatter_key_line,
    _extract_frontmatter_text,
    yaml_line_map as _yaml_line_map,
)

from .base import ContentBlock
from .devin_frontmatter import parse_devin_frontmatter
from .json_config import CopilotAgentMcpBlock, HookEventConfig, parse_hooks_events


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
    return _parse_frontmatter_content(content)


def _parse_frontmatter_content(
    content: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
    """Parse portable frontmatter without reading or writing a file."""
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


def _compose_frontmatter_document(content: Optional[str], fm: str) -> str:
    """Return *content* with its frontmatter replaced by normalized *fm*."""
    if not content:
        return f"---\n{fm}---\n"

    match = _FRONTMATTER_RE.match(content)
    if match:
        return f"---\n{fm}---\n{content[match.end() :]}"

    if not content.startswith("---"):
        return f"---\n{fm}---\n{content}"

    lines = content.split("\n")
    close_idx = None
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            close_idx = index
            break
    if close_idx is None:
        body_after = "\n".join(lines[1:])
        return f"---\n{fm}---\n{body_after}"

    body_after = "\n".join(lines[close_idx + 1 :])
    if body_after and not body_after.startswith("\n"):
        body_after = "\n" + body_after
    return f"---\n{fm}---{body_after}"


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
            and self.resolved_path == other.resolved_path
            and self.name == other.name
        )

    def __hash__(self):
        return hash((type(self), self.resolved_path, self.name))

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
        # Dialect parsers keep key-line bookkeeping. A preflight on a copy
        # leaves the attached block unchanged when an edit is refused.
        parser = (
            copy(self.parent)._parse_frontmatter_content
            if isinstance(self.parent, FrontmatteredBlock)
            else _parse_frontmatter_content
        )
        prefix = ""
        if content is not None:
            _fm, error, _line, file_body, _offset = parser(content)
            if error is not None:
                raise ValueError("Cannot rewrite body: frontmatter is malformed")
            prefix = content[: len(content) - len(file_body)]
        updated = prefix + new_body
        # Preflight the normalized text readers will see after the preserving
        # writer restores the file's original BOM and line-ending style.
        candidate = updated.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        _fm, error, _line, parsed_body, _offset = parser(candidate)
        if error is not None or parsed_body != new_body:
            raise ValueError("Cannot rewrite body: edit changes the frontmatter boundary")
        write_text_preserving(self.path, updated)
        self.body = new_body
        invalidate_read_caches(self.path)
        self.invalidate_find_cache()
        if isinstance(self.parent, FrontmatteredBlock):
            self.parent._invalidate_parsed()

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

    def _before_walk(self) -> None:
        self._ensure_parsed()  # frontmatter fields and body are children

    def _parse_frontmatter_file(
        self,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
        """Parse this file's frontmatter.

        Dialects override the content parser so reads and write preflight
        checks use the same frontmatter boundary.
        """
        content = read_text(self.path)
        if content is None:
            return None, f"Failed to read file: {self.path}", None, "", 0
        return self._parse_frontmatter_content(content)

    def _parse_frontmatter_content(
        self,
        content: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
        """The same dialect parser serves reads and body-write preflight checks."""
        return _parse_frontmatter_content(content)

    def _ensure_parsed(self) -> None:
        if self._fm_parsed is None:
            self._fm_parsed = self._parse_frontmatter_file()
            self._build_children()

    def _invalidate_parsed(self) -> None:
        self._fm_parsed = None
        # Rebuild children lazily; ancestors must not return the old fields/body.
        self.invalidate_find_cache()

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
    def hooks_events(self) -> Dict[str, List[HookEventConfig]]:
        """Parse a frontmatter ``hooks:`` key into event configs.

        Skill and agent frontmatter may declare hooks using the same schema as
        settings hooks (nested or flat), giving a checked-in, shareable vector
        for command execution.  Security rules scan these alongside settings
        and plugin ``hooks.json`` hooks.
        """
        return parse_hooks_events(self.field_value("hooks"))

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
        except (yaml.YAMLError, ValueError) as e:
            raise ValueError(f"Invalid YAML: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("Frontmatter must be a YAML mapping")

        fm = new_fm_text.rstrip("\n") + "\n"
        content = read_text(self.path)
        updated = _compose_frontmatter_document(content, fm)
        self.path.write_text(updated, encoding="utf-8")
        invalidate_read_caches(self.path)
        self._invalidate_parsed()


ParsedFrontmatterBlock = FrontmatteredBlock


# A key may be quoted: ``"alwaysApply": "true"`` declares the same field as
# the bare spelling, YAML allows it and Cursor's reader tolerates it.
# Rejecting it here would leave the field uncreated on the lenient path —
# unvalidated whenever Cursor-valid syntax like ``globs: **/*.ts`` forces
# that path — while ``_replace_key_line`` accepts the quoted form, and the
# reader and the fixer must agree on what declares a key.
_SIMPLE_FRONTMATTER_KEY_RE = re.compile(r"""^["']?([A-Za-z][A-Za-z0-9_-]*)["']?:[ \t]*(.*)$""")
_MDC_LIST_ITEM_RE = re.compile(r"^[ \t]*-[ \t]+(.*)$")


def _strip_inline_comment(value: str) -> str:
    """Drop a whitespace-preceded ``# ...`` suffix, honouring quotes.

    Mirrors YAML's comment rule so the two readers agree on commented
    lines: otherwise ``alwaysApply: true # applies globally`` reads as a
    string here while strict YAML reads the boolean, and the dialect
    correction would replace the correct boolean with the string —
    a type error on a valid file. A ``#`` inside quotes, or not preceded
    by whitespace, is data.
    """
    quote = ""
    for index, char in enumerate(value):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and index > 0 and value[index - 1] in " \t":
            return value[:index]
    return value


def _unquote(value: str) -> Tuple[Any, bool]:
    """Return (python value, was_quoted) for one raw ``.mdc`` scalar."""
    stripped = _strip_inline_comment(value).strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        return stripped[1:-1], True
    lowered = stripped.lower()
    if lowered in ("true", "false"):
        return lowered == "true", False
    return stripped, False


def _split_mdc_frontmatter(content: str) -> Optional[Tuple[str, str]]:
    """Split ``.mdc`` content into (frontmatter text, body), or ``None``.

    Deliberately independent of the shared YAML helpers: those decline an
    empty block (``---\\n---``), which Cursor reads perfectly well as a rule
    with no metadata.
    """
    lines = content.split("\n")
    # The opening delimiter must be exactly ``---``. ``----`` is a setext
    # heading rule, and treating it as an opener would swallow the prose up
    # to the next thematic break — hiding it from every content rule.
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    return None


def _parse_mdc_frontmatter(
    text: str, line_offset: int = 0
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Read ``.mdc`` frontmatter the permissive way Cursor does.

    Cursor's rule reader is not a YAML parser, and its own documentation
    ships frontmatter that ``yaml.safe_load`` rejects — ``globs: **/*.ts``
    starts with the YAML alias indicator, and an unquoted ``description``
    routinely contains a bare colon. Treating those as malformed produced a
    hard error asserting Cursor skips the file, which is untrue.

    Only the scalar and simple-list shapes Cursor documents are recognised;
    quoting is preserved so a quoted ``"true"`` stays the string that makes
    ``alwaysApply`` silently inert.

    Returns the parsed mapping and a key-to-file-line map. The line map is
    the whole reason this parser tracks positions: the strict YAML line
    mapper cannot read a file strict YAML rejected, so without one every
    violation on Cursor's own documented syntax would lose its line.
    """
    data: Dict[str, Any] = {}
    key_lines: Dict[str, int] = {}
    pending_list_key: Optional[str] = None
    for index, raw_line in enumerate(text.splitlines()):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        item = _MDC_LIST_ITEM_RE.match(raw_line)
        if item is not None and pending_list_key is not None:
            value, _ = _unquote(item.group(1))
            # The bare ``key:`` above stored ``None`` to mark "declared, no
            # scalar". The first item is what proves it was a list header,
            # so the list is created here rather than there — ``setdefault``
            # would hand back that ``None`` and append to it.
            existing = data.get(pending_list_key)
            if isinstance(existing, list):
                existing.append(value)
            else:
                data[pending_list_key] = [value]
            continue
        match = _SIMPLE_FRONTMATTER_KEY_RE.match(raw_line)
        if match is None:
            continue
        key, rest = match.group(1), match.group(2)
        key_lines[key] = index + line_offset
        if not rest.strip():
            # A bare ``key:`` opens a list block or declares an empty value.
            # Which one it is only becomes clear at the next line.
            pending_list_key = key
            data[key] = None
            continue
        pending_list_key = None
        value, _ = _unquote(rest)
        data[key] = value
    # Null values are kept: ``alwaysApply:`` with no value is a defect the
    # strict parser reports, and dropping the key here would make the
    # lenient path silently more permissive than the one it stands in for.
    return data, key_lines


@dataclass(eq=False)
class CursorRuleBlock(FrontmatteredBlock):
    """.cursor/rules/**/*.mdc files."""

    category: str = "instruction"

    #: Key-to-line map from the lenient reader, populated only when the
    #: lenient reader actually ran. Empty means the strict YAML line mapper
    #: is authoritative, as it is for every well-formed file.
    _mdc_key_lines: Optional[Dict[str, int]] = field(default=None, repr=False)

    def _parse_frontmatter_content(
        self,
        content: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
        """Fall back to Cursor's permissive dialect when strict YAML fails.

        Strict YAML runs first, so a well-formed file keeps exactly the
        types it has always had. Only a file YAML rejects — which Cursor
        itself accepts — reaches the lenient reader, and a file with no
        closing ``---`` still fails, because Cursor cannot read that either.
        """
        parsed = _parse_frontmatter_content(content)
        frontmatter, error, _error_line, _body, _fm_lines = parsed
        if frontmatter is not None:
            return self._apply_cursor_scalars(parsed, content)
        if error is None:
            return parsed

        if content.split("\n", 1)[0].strip() != "---":
            # The generic parser treats any ``---`` prefix as an opener, so a
            # setext rule like ``----`` arrives here as a malformed-frontmatter
            # error. Cursor sees a file with no frontmatter and reads the whole
            # thing as prose; reporting that it skips the rule is false.
            return None, None, None, content, 0
        split = _split_mdc_frontmatter(content)
        if split is None:
            # No closing delimiter: Cursor cannot find the body either, so
            # this really is unreadable and keeps the strict error.
            return parsed
        fm_text, body = split
        fm_line_count = content[: len(content) - len(body)].count("\n")
        # Frontmatter text starts on file line 2, after the opening ``---``,
        # and the parser counts its own lines from 0.
        data, key_lines = _parse_mdc_frontmatter(fm_text, line_offset=2)
        self._mdc_key_lines = key_lines
        return data, None, None, body, fm_line_count

    @staticmethod
    def _cursor_scalar(strict: Any, dialect: Any) -> Any:
        """Whichever of the two readings Cursor would actually see.

        Only a value the readers disagree about is replaced, and only in one
        direction: strict YAML typed it, the Cursor dialect kept it a string.
        A list is compared element-wise for the same reason.

        A *collection* is never traded for the dialect's scalar. The
        correction is for mistyped scalars — ``yes`` read as a bool — and a
        strict list is structure PyYAML got right. Flow style is where this
        bites: ``globs: [/etc/**, src/**]`` parses to a real list, while the
        line-oriented dialect reader returns the raw ``[/etc/**, src/**]``.
        Taking that string would hand the pattern splitter ``[/etc/**``,
        whose leading bracket hides the absolute path the rule exists to
        report. The same reasoning holds for a flow *mapping*: ``globs:
        {/etc/passwd,src}`` parses to a dict, but the dialect string
        ``{/etc/passwd,src}`` is kept whole by the pattern splitter (a comma
        inside braces is deliberately not split — the ambiguity is the
        finding), so its leading brace would likewise hide the absolute path.
        A mapping is reported as the wrong type instead.
        """
        if isinstance(dialect, str) and not isinstance(strict, (str, list, dict)):
            return dialect
        if isinstance(strict, list) and isinstance(dialect, list) and len(strict) == len(dialect):
            return [
                (
                    item_dialect
                    if isinstance(item_dialect, str) and not isinstance(item_strict, str)
                    else item_strict
                )
                for item_strict, item_dialect in zip(strict, dialect)
            ]
        return strict

    def _apply_cursor_scalars(
        self,
        parsed: Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int],
        content: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
        """Re-read strict-YAML scalars the way Cursor's ``.mdc`` reader does.

        Cursor does not parse ``.mdc`` frontmatter as YAML, so it sees the
        literal text where PyYAML sees a type. PyYAML also implements YAML
        1.1, where ``yes``/``no``/``on``/``off`` are booleans. Trusting
        either coercion produces findings that are backwards:

        - ``alwaysApply: yes`` becomes ``True``, so an inert rule is
          reported as always-on — the exact failure this rule exists to
          catch, and why ``_BOOLEAN_STRINGS`` lists ``yes``/``on`` as
          repairable spellings it could otherwise never receive.
        - ``description: no`` becomes ``False`` and ``description: 123``
          becomes an int, so valid routing text is rejected as the wrong
          type.
        - A ``globs`` item of ``- yes`` becomes ``True``, failing the
          list-of-strings check on a pattern Cursor reads fine.

        ``true`` and ``false`` are booleans to both readers and pass
        through untouched, as does anything the dialect also typed.
        """
        frontmatter = parsed[0]
        if not frontmatter:
            return parsed
        split = _split_mdc_frontmatter(content)
        if split is None:
            return parsed
        dialect, _lines = _parse_mdc_frontmatter(split[0])
        corrected = {
            key: self._cursor_scalar(value, dialect.get(key)) for key, value in frontmatter.items()
        }
        if corrected == frontmatter:
            return parsed
        return (corrected,) + parsed[1:]

    def key_line(self, key: str) -> Optional[int]:
        """Prefer the lenient reader's line map when it did the parsing."""
        self._ensure_parsed()
        if self._mdc_key_lines is not None:
            return self._mdc_key_lines.get(key)
        return super().key_line(key)


@dataclass(eq=False)
class CursorCommandBlock(FrontmatteredBlock):
    """.cursor/commands/**/*.md — Cursor slash commands."""

    category: str = "command"


@dataclass(eq=False)
class GrokCommandBlock(FrontmatteredBlock):
    """.grok/commands/*.md — Grok Build's legacy slash commands.

    Grok loads one as a project *skill*: ``grok inspect`` lists a
    ``.grok/commands/hello.md`` alongside ``.grok/skills/``. It is budgeted
    as a ``command`` all the same, because that is when the prose enters the
    context window — on demand, when the user invokes it.
    """

    category: str = "command"


@dataclass(eq=False)
class GrokAgentBlock(FrontmatteredBlock):
    """.grok/agents/*.md — Grok Build's project subagents."""

    category: str = "agent"
    _grok_key_lines: Dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _grok_frontmatter_text: str = field(default="", init=False, repr=False)

    def _parse_frontmatter_content(
        self,
        content: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
        """Read Grok's delimiter prefixes without changing other hosts.

        AgentDefinition::parse in Grok Build 1.0.13 trims leading whitespace,
        consumes an opening ``---`` prefix and stops YAML at the first
        ``\n---``. A following newline ends the closing delimiter line;
        without one, its suffix is the body. Keep body whitespace so
        content-rule spans still address the file.
        """
        self._grok_key_lines = {}
        self._grok_frontmatter_text = ""
        trimmed = content.lstrip()
        if not trimmed.startswith("---"):
            return None, None, None, content, 0
        start = len(content) - len(trimmed) + 3
        end = content.find("\n---", start)
        error = "Invalid frontmatter (malformed YAML or missing closing ---)"
        if end < 0:
            return None, error, None, content, 0
        text = content[start:end]
        self._grok_frontmatter_text = text
        offset = content[:start].count("\n")
        # One safe LibYAML-backed parse supplies both data and source marks;
        # field lookups must not reparse YAML for every key.
        loader = _SAFE_LOADER(text)
        try:
            node = loader.get_single_node()
            if not isinstance(node, yaml.MappingNode):
                return None, error, None, content, 0
            key_lines = {
                key.value: key.start_mark.line + offset + 1
                for key, _value in node.value
                if isinstance(key, yaml.ScalarNode) and key.tag == "tag:yaml.org,2002:str"
            }
            data = loader.construct_document(node)
        except (yaml.YAMLError, ValueError, RecursionError) as exc:
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + offset + 1 if mark is not None else None
            return None, error, line, content, 0
        finally:
            loader.dispose()
        if not isinstance(data, dict):
            return None, error, None, content, 0
        self._grok_key_lines = key_lines
        after_closing = end + 4
        newline = content.find("\n", after_closing)
        body_start = newline + 1 if newline >= 0 else after_closing
        return data, None, None, content[body_start:], content[:body_start].count("\n")

    def key_line(self, key: str) -> Optional[int]:
        self._ensure_parsed()
        return self._grok_key_lines.get(key)

    def read_frontmatter_text(self) -> str:
        self._ensure_parsed()
        return self._grok_frontmatter_text

    def line_map(self) -> Dict[str, int]:
        self._ensure_parsed()
        return dict(self._grok_key_lines)


@dataclass(eq=False)
class AntigravityAgentBlock(FrontmatteredBlock):
    """``<customization root>/agents/*.md`` — Antigravity's subagents.

    Deliberately not an :class:`AgentBlock`: that class is what the Claude
    agent-frontmatter rules select, and Antigravity's own frontmatter
    contract is unmeasured. Budgeted as a ``command`` would be wrong too —
    a subagent is loaded when it is delegated to, which is the ``agent``
    role every peer tool's subagents carry.

    For the same reason this type is absent from the traversal list in
    ``content-description-routing``, while both Antigravity repository
    types *do* activate that rule — for a plugin's skills and for the
    prose the shared plugin pass attaches. A decision, not an oversight:
    Antigravity does route by description, its skills page saying the agent
    picks from names and descriptions, but no frontmatter field for this
    file was reachable offline, and a routing rule with no measured field
    to read would report against a contract nobody confirmed. The
    maintenance reference records it under "Not covered yet".
    """

    category: str = "agent"


@dataclass(eq=False)
class CopilotPromptBlock(FrontmatteredBlock):
    """.github/prompts/**/*.prompt.md — Copilot prompt files."""

    category: str = "command"


@dataclass(eq=False)
class CopilotAgentBlock(FrontmatteredBlock):
    """.github/agents/**/*.md and legacy .github/chatmodes/**/*.chatmode.md."""

    category: str = "agent"

    @property
    def effective_target(self) -> Optional[str]:
        """Return the declared target, or the legacy chatmode default.

        Current ``.github/agents/**/*.md`` files target both environments
        when the field is omitted. Only legacy VS Code chatmodes have a
        single-environment default; an explicit valid target always wins.
        """
        declared = self.field_value("target")
        if declared in ("vscode", "github-copilot"):
            return declared
        parts = self.path.parts
        for index in range(len(parts) - 2, -1, -1):
            if parts[index] != ".github":
                continue
            if parts[index + 1] == "chatmodes":
                return "vscode"
            if parts[index + 1] == "agents":
                return None
        return None

    @property
    def supports_vscode(self) -> bool:
        return self.effective_target != "github-copilot"

    @property
    def supports_github_copilot(self) -> bool:
        return self.effective_target != "vscode"

    @property
    def hooks_events(self) -> Dict[str, List[HookEventConfig]]:
        """Parse embedded hooks while retaining each command's YAML line."""
        if not self.supports_vscode:
            return {}
        # A top-level YAML merge can supply ``hooks`` without giving the
        # merged key its own source line. The compatibility parse has already
        # resolved merges into FrontmatterField children, so it is the cheap,
        # merge-aware presence check; the ruamel parse below retains the
        # anchor's nested command lines for security findings.
        if self.field("hooks") is None:
            return {}
        frontmatter, error, _error_line = read_frontmatter_commented(self.path)
        if error or not isinstance(frontmatter, dict):
            return {}
        events = parse_hooks_events(frontmatter.get("hooks"), line_offset=1, default_type="command")
        # VS Code executes command strings; it ignores Claude's separate args.
        for entries in events.values():
            for entry in entries:
                for handler in entry.handlers:
                    handler.args = None
        return events

    def _build_children(self) -> None:
        """Attach embedded MCP configuration as a shared lint-tree role."""
        self.children = [
            child for child in self.children if not isinstance(child, CopilotAgentMcpBlock)
        ]
        super()._build_children()
        # YAML merges do not give the merged root key its own source line, but
        # the resolved field still carries source lines for nested entries.
        mcp_field = self.field("mcp-servers")
        if mcp_field is None:
            return
        if not self.supports_github_copilot:
            return
        frontmatter, error, _error_line = read_frontmatter_commented(self.path)
        if error or not isinstance(frontmatter, dict):
            return
        servers = frontmatter.get("mcp-servers")
        # The format rule owns the top-level type error. Only a mapping can
        # be meaningfully handed to the shared MCP rules; attaching an
        # invalid scalar/list too would duplicate that root diagnostic.
        if isinstance(servers, dict):
            source_line = mcp_field.field_line
            if source_line is None:
                # A merge-inherited root has no local position. Anchor
                # aggregate policy findings to the first literal server key,
                # which is still traceable in the source anchor mapping.
                for server_name in servers:
                    nested_line = commented_key_line(servers, server_name)
                    if nested_line is not None:
                        source_line = nested_line + 1
                        break
            self.children.append(
                CopilotAgentMcpBlock(
                    path=self.path,
                    inline_data={"mcpServers": servers},
                    source_line=source_line,
                    parent=self,
                )
            )


@dataclass(eq=False)
class OpenCodeCommandBlock(FrontmatteredBlock):
    """``.opencode/commands/**/*.md`` — OpenCode slash commands.

    Also the OpenCode 1.x ``.opencode/command/`` spelling, which 2.0 still
    loads. Budgeted as a ``command``: the file enters the context window
    when the user types ``/name``, not on every turn.
    """

    category: str = "command"


@dataclass(eq=False)
class OpenCodeAgentBlock(FrontmatteredBlock):
    """``.opencode/agents/**/*.md`` — an OpenCode agent of either kind.

    Covers the 1.x ``agent/`` directory and the older ``mode/`` spelling of
    the same thing, both of which 2.0 still loads. Under ``agent(s)/`` the
    file's own ``mode`` field says which kind it is: a ``primary`` agent is
    one a person cycles to, while ``subagent`` and the default ``all`` are
    delegated to on their descriptions. Under ``mode(s)/`` the directory
    decides instead — OpenCode types every file there ``primary`` whatever
    the frontmatter says. Rules that care about that distinction read both;
    the block type holds every kind.
    """

    category: str = "agent"


@dataclass(eq=False)
class CommandBlock(FrontmatteredBlock):
    """commands/*.md in plugins."""

    category: str = "command"

    def provenance_dir(self) -> Optional[Path]:
        # The owner the attach recorded, which is the claimed directory
        # itself. The fallback is the ``<claimed dir>/commands/*.md`` layout
        # (one level — see ``_add_plugin_prose``), and it is a guess: a Grok
        # manifest may point ``commands`` at any contained path, and
        # ``parent.parent`` on ``tools/commands/x.md`` names an intermediate
        # directory no ecosystem claims — which puts every Claude-scoped
        # rule back on content this repository declared for another host.
        # Repository-level ``.claude/commands/*.md`` carries no owner and
        # keeps the layout answer.
        return self.plugin_owner or self.path.parent.parent

    def section(self, heading: str, level: int = 2) -> str:
        content = read_text(self.path)
        if content is None:
            return ""
        return extract_section(content, heading, level)


@dataclass(eq=False)
class AgentBlock(FrontmatteredBlock):
    """agents/*.md in plugins or APM agent files."""

    category: str = "agent"

    def provenance_dir(self) -> Optional[Path]:
        # Same rule as CommandBlock: the recorded owner first, the one-level
        # layout as the fallback. APM agent files carry no owner and land on
        # ``.apm/``, which no ecosystem claims, keeping them in every scope.
        return self.plugin_owner or self.path.parent.parent


@dataclass(eq=False)
class SkillBlock(FrontmatteredBlock):
    """SKILL.md in skills."""

    category: str = "skill"


@dataclass(eq=False)
class DevinRuleBlock(FrontmatteredBlock):
    """A rule under ``.devin/rules`` or legacy ``.windsurf/rules``."""

    category: str = "instruction"
    _devin_key_lines: Optional[Dict[str, int]] = field(default=None, repr=False)

    @staticmethod
    def _quote_plain_glob_scalars(text: str) -> Tuple[str, bool]:
        """Quote Devin's documented bare ``*`` glob scalar for YAML parsing.

        Devin documents ``globs: **/*.test.ts``, while YAML reserves a leading
        ``*`` for aliases. Only that top-level field is rewritten, and only in
        the in-memory parse source, so unrelated malformed YAML still fails.
        """
        changed = False
        lines = text.splitlines()
        for index, raw_line in enumerate(lines):
            match = _SIMPLE_FRONTMATTER_KEY_RE.match(raw_line)
            if match is None or match.group(1) != "globs":
                continue
            rest = match.group(2)
            uncommented = _strip_inline_comment(rest)
            value = uncommented.strip()
            if not value.startswith("*"):
                continue
            value_end = len(uncommented.rstrip())
            lines[index] = raw_line[: match.start(2)] + json.dumps(value) + rest[value_end:]
            changed = True
        return "\n".join(lines), changed

    def _parse_frontmatter_content(
        self,
        content: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
        parsed = parse_devin_frontmatter(content)
        if parsed[0] is not None or parsed[1] is None:
            return parsed

        split = _split_mdc_frontmatter(content)
        if split is None:
            return parsed
        fm_text, body = split
        parse_text, changed = self._quote_plain_glob_scalars(fm_text)
        if not changed:
            return parsed

        frontmatter, _error, error_line, parsed_body, _ = parse_devin_frontmatter(
            f"---\n{parse_text}\n---\n{body}"
        )
        if frontmatter is None:
            return (
                None,
                "Invalid frontmatter (malformed YAML or missing closing ---)",
                error_line,
                parsed_body,
                0,
            )

        self._devin_key_lines = {}
        for index, line in enumerate(fm_text.splitlines(), start=2):
            match = _SIMPLE_FRONTMATTER_KEY_RE.match(line)
            if match is not None:
                self._devin_key_lines[match.group(1)] = index
        fm_line_count = content[: len(content) - len(body)].count("\n")
        return frontmatter, None, None, body, fm_line_count

    def key_line(self, key: str) -> Optional[int]:
        self._ensure_parsed()
        if self._devin_key_lines is not None:
            return self._devin_key_lines.get(key)
        return super().key_line(key)


@dataclass(eq=False)
class DevinSkillBlock(FrontmatteredBlock):
    """A Devin-native SKILL.md whose frontmatter is optional."""

    category: str = "skill"

    def _parse_frontmatter_content(
        self,
        content: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
        return parse_devin_frontmatter(content, skill=True)


@dataclass(eq=False)
class PluginRuleBlock(FrontmatteredBlock):
    """rules/*.md in plugins."""

    category: str = "rule"
