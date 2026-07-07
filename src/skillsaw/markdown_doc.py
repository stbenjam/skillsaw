"""
Markdown AST facade for skillsaw.

Parses markdown once with markdown-it-py (strict CommonMark) and exposes the
structural pieces rules need — links, code spans, fences, HTML comments,
headings, prose lines, and plain-text segments — with exact source positions.

The contract is **AST for reading, surgical span splices for writing**:
detection and fixes share the same token spans, and :func:`splice` applies
``(file_line, col_start, col_end, replacement)`` edits without ever rendering
the AST back to markdown (round-trip rendering would reformat whole files).

Positions
---------

* ``body_line`` — 1-based line number within the parsed body text.
* ``file_line`` — 1-based line number in the containing file, composed
  through ``line_offset`` / ``line_map`` exactly like
  ``ContentBlock.file_line()``.
* ``col_start`` / ``col_end`` — 0-based character offsets within the line
  (``col_end`` is exclusive).  Columns are ``None`` when the source cannot
  be mapped exactly (rare tab-expansion corners); line numbers are always
  exact, so detection never regresses — only the surgical fix is skipped.

markdown-it-py inline children carry no source offsets, so columns are
recovered by walking each inline token's children while progressively
consuming its mapped raw source lines, re-accounting blockquote/list
prefixes and lazy continuations (the "column glue").
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from markdown_it import MarkdownIt

__all__ = [
    "MarkdownDoc",
    "MarkdownLink",
    "MarkdownCodeSpan",
    "MarkdownFence",
    "MarkdownHtmlComment",
    "MarkdownHeading",
    "MarkdownTextSegment",
    "splice",
    "file_span",
]


def _make_parser() -> MarkdownIt:
    md = MarkdownIt()  # CommonMark preset
    # Keep ``text_special`` tokens (backslash escapes and entity references)
    # instead of joining them back into plain text.  With them preserved,
    # every ``text`` child is a verbatim slice of the source, which is what
    # makes exact column recovery possible.
    md.disable("text_join", ignoreInvalid=True)
    return md


_PARSER = _make_parser()

_HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
_REF_DEF_RE = re.compile(r"^[ \t]{0,3}\[([^\]]+)\]:[ \t]+")


@lru_cache(maxsize=128)
def _parse_cached(body: str):
    """Parse *body* once and share the token stream.

    Several consumers parse the same text (content blocks, suppression maps
    for the same file); tokens are treated as read-only so sharing is safe.
    """
    return _PARSER.parse(body)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MarkdownLink:
    """An inline link, image, autolink, or resolved reference link."""

    text: str
    href: str  # raw destination as written in source; resolved for refs/autolinks
    title: Optional[str]
    body_line: int  # construct start line (the ``[``)
    file_line: int
    dest_body_line: Optional[int] = None
    dest_file_line: Optional[int] = None
    dest_col_start: Optional[int] = None
    dest_col_end: Optional[int] = None
    is_image: bool = False
    is_autolink: bool = False
    is_reference: bool = False

    @property
    def has_dest_span(self) -> bool:
        return self.dest_col_start is not None and self.dest_col_end is not None


@dataclass
class MarkdownCodeSpan:
    """An inline code span. The span includes the backtick delimiters."""

    content: str
    markup: str  # the backtick run, e.g. "`" or "``"
    body_line: int
    file_line: int
    col_start: Optional[int] = None
    col_end: Optional[int] = None
    multiline: bool = False
    in_link: bool = False


@dataclass
class MarkdownFence:
    """A fenced or indented code block. Line range includes the delimiters."""

    info: str
    body_line_start: int
    body_line_end: int
    file_line_start: int
    file_line_end: int
    indented: bool = False
    markup: str = ""  # opening fence run ("```", "~~~~", …); empty for indented blocks
    nested: bool = False  # inside a container (blockquote, list item)


@dataclass
class MarkdownHtmlComment:
    """An HTML comment (block or inline). ``text`` is the inner comment body."""

    text: str
    body_line_start: int
    body_line_end: int
    file_line_start: int
    file_line_end: int


@dataclass
class MarkdownHeading:
    """An ATX or setext heading."""

    level: int
    text: str
    body_line: int  # first line of the heading construct
    file_line: int
    body_line_end: int  # line after the heading construct (section content start)
    setext: bool = False


@dataclass
class MarkdownTextSegment:
    """A run of plain prose text (one inline ``text`` token, never multi-line)."""

    text: str
    body_line: int
    file_line: int
    col_start: Optional[int]
    col_end: Optional[int]
    in_link: bool = False


# ---------------------------------------------------------------------------
# splice
# ---------------------------------------------------------------------------


def splice(content: str, edits: Sequence[Tuple[int, int, int, str]]) -> str:
    """Apply ``(file_line, col_start, col_end, replacement)`` edits to *content*.

    Edits are applied right-to-left within each line so earlier spans stay
    valid.  Lines are 1-based; columns are 0-based offsets within the line
    (excluding the line ending).  Out-of-range or overlapping edits are
    skipped rather than applied incorrectly.
    """
    if not edits:
        return content
    lines = content.splitlines(keepends=True)
    by_line: Dict[int, List[Tuple[int, int, str]]] = {}
    for file_line, col_start, col_end, replacement in edits:
        by_line.setdefault(file_line, []).append((col_start, col_end, replacement))
    for file_line, line_edits in by_line.items():
        idx = file_line - 1
        if idx < 0 or idx >= len(lines):
            continue
        raw = lines[idx]
        ending_len = len(raw) - len(raw.rstrip("\r\n"))
        text_len = len(raw) - ending_len
        min_start = text_len + 1
        for col_start, col_end, replacement in sorted(
            line_edits, key=lambda e: (e[0], e[1]), reverse=True
        ):
            if col_start < 0 or col_end > text_len or col_start > col_end:
                continue
            if col_end > min_start:
                continue  # overlaps an already-applied edit
            raw = raw[:col_start] + replacement + raw[col_end:]
            min_start = col_start
        lines[idx] = raw
    return "".join(lines)


def file_span(
    doc: "MarkdownDoc",
    file_content: str,
    file_line: int,
    body_line: int,
    col_start: int,
    col_end: int,
) -> Optional[Tuple[int, int]]:
    """Translate body-relative columns to file columns, verifying the text.

    For most blocks body lines equal file lines and this is the identity.
    For bodies extracted from YAML scalars (``.coderabbit.yaml`` instructions,
    promptfoo prompts) the file line carries extra indentation; the shift is
    recovered by locating the body line within the file line.  Returns
    ``None`` when the span cannot be verified — callers must skip the edit
    rather than risk touching the wrong characters.
    """
    lines = file_content.split("\n")
    idx = file_line - 1
    if idx < 0 or idx >= len(lines):
        return None
    raw = lines[idx].rstrip("\r")
    expected = doc.line(body_line)[col_start:col_end]
    if not expected:
        return None
    if raw[col_start:col_end] == expected and raw.startswith(doc.line(body_line)):
        return (col_start, col_end)
    body_text = doc.line(body_line)
    if body_text:
        delta = raw.find(body_text)
        if delta >= 0 and raw[col_start + delta : col_end + delta] == expected:
            return (col_start + delta, col_end + delta)
    return None


# ---------------------------------------------------------------------------
# Column glue
# ---------------------------------------------------------------------------


class _ContentMap:
    """Maps offsets in an inline token's ``content`` string to source positions.

    The inline content is the raw source with block prefixes (blockquote
    markers, list indents) stripped and lines joined by ``\\n``.  For each
    content line we locate where it begins in the raw source line; columns
    inside that line then translate by simple offset.
    """

    def __init__(self, body_lines: List[str], map_start: int, content: str):
        # entries: (content_offset_of_line_start, body_line_0based, raw_col or None)
        self.entries: List[Tuple[int, int, Optional[int]]] = []
        pos = 0
        for i, content_line in enumerate(content.split("\n")):
            body_line0 = map_start + i
            raw = body_lines[body_line0] if 0 <= body_line0 < len(body_lines) else ""
            col: Optional[int] = None
            if content_line:
                idx = raw.find(content_line)
                if idx >= 0:
                    col = idx
                else:
                    # Tab expansion in block prefixes can prepend spaces to the
                    # content line that don't exist in the raw source.  Try
                    # matching without the synthetic leading spaces.
                    stripped = content_line.lstrip(" ")
                    if stripped:
                        idx = raw.find(stripped)
                        if idx >= 0:
                            adjusted = idx - (len(content_line) - len(stripped))
                            col = adjusted if adjusted >= 0 else None
            else:
                col = 0
            self.entries.append((pos, body_line0, col))
            pos += len(content_line) + 1
        # ``entries`` is sorted by its first field (line-start offset), which is
        # strictly increasing.  Keep a parallel list of just those offsets so
        # ``locate`` can binary-search instead of scanning linearly — the scan
        # was O(n) per call and ``locate`` is called ~once per content line, so
        # a large single paragraph made lint O(n^2) (see issue #318).
        self._starts: List[int] = [e[0] for e in self.entries]

    def locate(self, content_pos: int) -> Tuple[int, Optional[int]]:
        """Return (body_line_0based, raw_col or None) for a content offset."""
        # Rightmost entry whose start offset is <= content_pos.  ``_starts[0]``
        # is always 0, so the index never goes negative for a valid offset;
        # clamp defensively anyway.
        idx = bisect.bisect_right(self._starts, content_pos) - 1
        if idx < 0:
            idx = 0
        line_start, body_line0, raw_col = self.entries[idx]
        if raw_col is None:
            return body_line0, None
        return body_line0, raw_col + (content_pos - line_start)


class _InlineWalker:
    """Walks an inline token's children, tracking a cursor into its content.

    Every child token's source span is recovered by consuming the expected
    literal text at the cursor.  When the source diverges from expectations
    (exotic constructs, tab corners) the walker resyncs with a forward
    search or, failing that, degrades that construct's columns to ``None``.
    """

    def __init__(self, doc: "MarkdownDoc", inline_token) -> None:
        self.doc = doc
        self.content: str = inline_token.content
        self.map_start: int = inline_token.map[0] if inline_token.map else 0
        self.cmap = _ContentMap(doc._lines, self.map_start, self.content)
        self.pos = 0
        self.lost = False  # cursor no longer trustworthy

        self.links: List[MarkdownLink] = []
        self.code_spans: List[MarkdownCodeSpan] = []
        self.segments: List[MarkdownTextSegment] = []
        self.html_comments: List[MarkdownHtmlComment] = []
        # spans of verbatim regions (code spans / inline html comments) in
        # content coordinates, for prose blanking
        self.verbatim_spans: List[Tuple[int, int]] = []

        self._link_stack: List[Dict] = []

    # -- public ----------------------------------------------------------

    def walk(self, children) -> None:
        self._walk(children or [], in_image_alt=False)

    # -- consumption helpers ----------------------------------------------

    def _expect(self, literal: str) -> Optional[int]:
        """Consume *literal* at the cursor, resyncing forward if needed.

        Returns the content offset where the literal was found, or ``None``
        if it could not be located (cursor becomes untrusted).
        """
        if not literal:
            return self.pos
        idx = self.content.find(literal, self.pos)
        if idx < 0:
            self.lost = True
            return None
        self.pos = idx + len(literal)
        return idx

    def _consume_break(self) -> None:
        """Consume a soft/hard break: optional trailing spaces/backslash + newline."""
        idx = self.content.find("\n", self.pos)
        if idx < 0:
            self.lost = True
            return
        self.pos = idx + 1
        # Inline parsing skips leading whitespace on continuation lines.
        while self.pos < len(self.content) and self.content[self.pos] in " \t":
            self.pos += 1

    def _skip_ws(self, i: int) -> int:
        while i < len(self.content) and self.content[i] in " \t\n":
            i += 1
        return i

    # -- walking -----------------------------------------------------------

    def _walk(self, children, in_image_alt: bool) -> None:
        for token in children:
            ttype = token.type
            if ttype == "text":
                self._handle_text(token, in_image_alt)
            elif ttype == "text_special":
                self._expect(token.markup or token.content)
            elif ttype == "code_inline":
                self._handle_code_inline(token, in_image_alt)
            elif ttype in ("softbreak", "hardbreak"):
                self._consume_break()
            elif ttype in ("em_open", "em_close", "strong_open", "strong_close"):
                self._expect(token.markup)
            elif ttype == "html_inline":
                self._handle_html_inline(token)
            elif ttype == "link_open":
                self._handle_link_open(token)
            elif ttype == "link_close":
                self._handle_link_close(token)
            elif ttype == "image":
                self._handle_image(token)
            else:
                # Unknown construct: positions can no longer be trusted.
                self.lost = True

    def _position(self, content_pos: int) -> Tuple[int, Optional[int]]:
        body_line0, col = self.cmap.locate(content_pos)
        if self.lost:
            col = None
        return body_line0, col

    def _handle_text(self, token, in_image_alt: bool) -> None:
        start = self._expect(token.content)
        in_link = bool(self._link_stack) or in_image_alt
        if start is None:
            # Line/column unknown; report at the inline start as a fallback.
            body_line0, col = self.map_start, None
            end_col: Optional[int] = None
        else:
            body_line0, col = self._position(start)
            end_col = col + len(token.content) if col is not None else None
        self.segments.append(
            MarkdownTextSegment(
                text=token.content,
                body_line=body_line0 + 1,
                file_line=self.doc.file_line(body_line0 + 1),
                col_start=col,
                col_end=end_col,
                in_link=in_link,
            )
        )

    def _handle_code_inline(self, token, in_image_alt: bool = False) -> None:
        in_link = bool(self._link_stack) or in_image_alt
        markup = token.markup or "`"
        start = self._expect(markup)
        if start is None:
            self._emit_code_span(token, None, None, in_link)
            return
        # Find the closing run of exactly the same length.
        close = -1
        search = self.pos
        while True:
            idx = self.content.find(markup, search)
            if idx < 0:
                break
            before_ok = idx == 0 or self.content[idx - 1] != "`"
            after = idx + len(markup)
            after_ok = after >= len(self.content) or self.content[after] != "`"
            if before_ok and after_ok and idx >= self.pos:
                close = idx
                break
            search = idx + 1
        if close < 0:
            self.lost = True
            self._emit_code_span(token, None, None, in_link)
            return
        inner = self.content[self.pos : close]
        end = close + len(markup)
        self.pos = end
        # Verify the inner source matches the token content (modulo the
        # CommonMark one-space padding rule and newline-to-space mapping).
        normalized = inner.replace("\n", " ")
        if (
            len(normalized) >= 2
            and normalized.startswith(" ")
            and normalized.endswith(" ")
            and normalized.strip()
        ):
            padded_match = normalized[1:-1] == token.content
        else:
            padded_match = False
        if normalized != token.content and not padded_match:
            self.lost = True
            self._emit_code_span(token, None, None, in_link)
            return
        self.verbatim_spans.append((start, end))
        self._emit_code_span(token, start, end, in_link)

    def _emit_code_span(
        self, token, start: Optional[int], end: Optional[int], in_link: bool = False
    ) -> None:
        if start is not None:
            body_line0, col_start = self._position(start)
        else:
            body_line0, col_start = self.map_start, None
        col_end: Optional[int] = None
        multiline = False
        if start is not None and end is not None:
            end_line0, col_end = self._position(end)
            if end_line0 != body_line0:
                multiline = True
                col_start = None
                col_end = None
        self.code_spans.append(
            MarkdownCodeSpan(
                content=token.content,
                markup=token.markup or "`",
                body_line=body_line0 + 1,
                file_line=self.doc.file_line(body_line0 + 1),
                col_start=col_start,
                col_end=col_end,
                multiline=multiline,
                in_link=in_link,
            )
        )

    def _handle_html_inline(self, token) -> None:
        start = self._expect(token.content)
        if start is None:
            return
        end = start + len(token.content)
        match = _HTML_COMMENT_RE.fullmatch(token.content)
        if match:
            self.verbatim_spans.append((start, end))
            start_line0, _ = self.cmap.locate(start)
            end_line0, _ = self.cmap.locate(max(start, end - 1))
            self.html_comments.append(
                MarkdownHtmlComment(
                    text=match.group(1),
                    body_line_start=start_line0 + 1,
                    body_line_end=end_line0 + 1,
                    file_line_start=self.doc.file_line(start_line0 + 1),
                    file_line_end=self.doc.file_line(end_line0 + 1),
                )
            )

    def _handle_link_open(self, token) -> None:
        if token.info == "auto":
            start = self._expect("<")
            self._link_stack.append(
                {"auto": True, "start": start, "href": token.attrGet("href") or ""}
            )
        else:
            start = self._expect("[")
            self._link_stack.append(
                {
                    "auto": False,
                    "start": start,
                    "href": token.attrGet("href") or "",
                    "title": token.attrGet("title"),
                    "text_from": len(self.segments),
                }
            )

    def _handle_link_close(self, token) -> None:
        if not self._link_stack:
            self.lost = True
            return
        info = self._link_stack.pop()
        if info["auto"]:
            close = self._expect(">")
            self._emit_autolink(info, close)
            return
        text = "".join(s.text for s in self.segments[info.get("text_from", 0) :])
        bracket = self._expect("]")
        if bracket is None:
            self._emit_link(info, text, None, None, None, is_reference=True)
            return
        parsed = self._parse_link_tail()
        if parsed is None:
            self._emit_link(info, text, None, None, None, is_reference=True)
            return
        dest_raw, dest_start, dest_end, title, is_reference = parsed
        self._emit_link(info, text, dest_raw, dest_start, dest_end, is_reference, title)

    def _parse_link_tail(self):
        """Parse ``(dest "title")`` or a reference label after the closing ``]``.

        Returns ``(dest_raw, dest_start, dest_end, title, is_reference)`` or
        ``None`` when the tail cannot be parsed (cursor stays put).
        ``dest_*`` are ``None`` for reference-style links.
        """
        c = self.content
        n = len(c)
        i = self.pos
        if i < n and c[i] == "(":
            i = self._skip_ws(i + 1)
            title: Optional[str] = None
            if i < n and c[i] == ")":
                # Empty destination: [text]()
                self.pos = i + 1
                return ("", i, i, None, False)
            if i < n and c[i] == "<":
                dest_start = i + 1
                j = dest_start
                while j < n and c[j] not in "<>\n":
                    j += 2 if c[j] == "\\" else 1
                if j >= n or c[j] != ">":
                    return None
                dest_end = j
                i = j + 1
            else:
                dest_start = i
                depth = 0
                j = i
                while j < n:
                    ch = c[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch in " \t\n":
                        break
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        if depth == 0:
                            break
                        depth -= 1
                    j += 1
                dest_end = j
                i = j
            i = self._skip_ws(i)
            if i < n and c[i] in "\"'(":
                closer = {'"': '"', "'": "'", "(": ")"}[c[i]]
                j = i + 1
                while j < n and c[j] != closer:
                    j += 2 if c[j] == "\\" else 1
                if j >= n:
                    return None
                title = c[i + 1 : j]
                i = self._skip_ws(j + 1)
            if i < n and c[i] == ")":
                self.pos = i + 1
                return (c[dest_start:dest_end], dest_start, dest_end, title, False)
            return None
        if i < n and c[i] == "[":
            j = c.find("]", i + 1)
            if j >= 0:
                self.pos = j + 1
                return ("", None, None, None, True)
        # Shortcut reference: nothing follows the closing bracket.
        return ("", None, None, None, True)

    def _emit_link(
        self,
        info: Dict,
        text: str,
        dest_raw: Optional[str],
        dest_start: Optional[int],
        dest_end: Optional[int],
        is_reference: bool,
        title: Optional[str] = None,
        is_image: bool = False,
    ) -> None:
        start = info.get("start")
        if start is not None:
            body_line0, _ = self._position(start)
        else:
            body_line0 = self.map_start
        dest_body_line = dest_file_line = dest_col_start = dest_col_end = None
        if dest_start is not None and dest_end is not None:
            ds_line0, ds_col = self._position(dest_start)
            de_line0, de_col = self._position(
                max(dest_start, dest_end - 1) if dest_end > dest_start else dest_end
            )
            if ds_col is not None and de_col is not None and ds_line0 == de_line0:
                dest_body_line = ds_line0 + 1
                dest_file_line = self.doc.file_line(dest_body_line)
                dest_col_start = ds_col
                dest_col_end = ds_col + (dest_end - dest_start)
        href = dest_raw if dest_raw else info.get("href", "")
        self.links.append(
            MarkdownLink(
                text=text,
                href=href,
                title=title if title is not None else info.get("title"),
                body_line=body_line0 + 1,
                file_line=self.doc.file_line(body_line0 + 1),
                dest_body_line=dest_body_line,
                dest_file_line=dest_file_line,
                dest_col_start=dest_col_start,
                dest_col_end=dest_col_end,
                is_image=is_image,
                is_reference=is_reference,
            )
        )

    def _emit_autolink(self, info: Dict, close: Optional[int]) -> None:
        start = info.get("start")
        if start is not None:
            body_line0, _ = self._position(start)
        else:
            body_line0 = self.map_start
        self.links.append(
            MarkdownLink(
                text=info.get("href", ""),
                href=info.get("href", ""),
                title=None,
                body_line=body_line0 + 1,
                file_line=self.doc.file_line(body_line0 + 1),
                is_autolink=True,
            )
        )

    def _handle_image(self, token) -> None:
        start = self._expect("![")
        text_from = len(self.segments)
        self._walk(token.children or [], in_image_alt=True)
        bracket = self._expect("]")
        text = "".join(s.text for s in self.segments[text_from:])
        info = {"start": start, "href": token.attrGet("src") or "", "title": token.attrGet("title")}
        if bracket is None:
            self._emit_link(info, text, None, None, None, is_reference=True, is_image=True)
            return
        parsed = self._parse_link_tail()
        if parsed is None:
            self._emit_link(info, text, None, None, None, is_reference=True, is_image=True)
            return
        dest_raw, dest_start, dest_end, title, is_reference = parsed
        self._emit_link(
            info, text, dest_raw, dest_start, dest_end, is_reference, title, is_image=True
        )


# ---------------------------------------------------------------------------
# MarkdownDoc
# ---------------------------------------------------------------------------


class MarkdownDoc:
    """A parsed markdown body with file-absolute position accessors.

    Args:
        body: The markdown text (after frontmatter removal, if any).
        line_offset: Added to 1-based body lines to produce file lines.
        line_map: Optional callable overriding the offset translation —
            the same contract as ``ContentBlock._line_map``.
    """

    def __init__(
        self,
        body: str,
        line_offset: int = 0,
        line_map: Optional[Callable[[int], int]] = None,
    ) -> None:
        self.body = body
        self._line_offset = line_offset
        self._line_map = line_map
        self._lines: List[str] = body.split("\n")
        self._tokens = _parse_cached(body) if body else []
        self._walked = False
        self._links: List[MarkdownLink] = []
        self._code_spans: List[MarkdownCodeSpan] = []
        self._segments: List[MarkdownTextSegment] = []
        self._inline_comments: List[MarkdownHtmlComment] = []
        self._inline_verbatim: List[Tuple[int, int, int]] = []  # (map_start, start, end)
        self._inline_maps: List[Tuple[int, str, List[Tuple[int, int]]]] = []
        self._prose: Optional[List[str]] = None
        self._prose_text: Optional[str] = None

    # -- positions ----------------------------------------------------------

    def file_line(self, body_line: int) -> int:
        """Translate a 1-based body line number to a 1-based file line number."""
        if self._line_map is not None:
            return self._line_map(body_line)
        return body_line + self._line_offset

    def line(self, body_line: int) -> str:
        """Return the raw body line text (1-based)."""
        if 1 <= body_line <= len(self._lines):
            return self._lines[body_line - 1]
        return ""

    @property
    def body_line_count(self) -> int:
        return len(self._lines)

    # -- inline walking -----------------------------------------------------

    def _ref_def_dest_spans(self) -> Dict[str, List[Tuple[int, int, int]]]:
        """Parse reference-definition destinations from body lines.

        Returns a dict mapping raw destination text to a list of
        ``(body_line_1based, col_start, col_end)`` tuples.  Lines inside
        fenced/indented code blocks are excluded.
        """
        fence_lines: set = set()
        for f in self.fences():
            for bl in range(f.body_line_start, f.body_line_end + 1):
                fence_lines.add(bl)
        result: Dict[str, List[Tuple[int, int, int]]] = {}
        for i, line in enumerate(self._lines):
            body_line = i + 1
            if body_line in fence_lines:
                continue
            m = _REF_DEF_RE.match(line)
            if m is None:
                continue
            pos = m.end()
            if pos < len(line) and line[pos] == "<":
                dest_start = pos + 1
                end = line.find(">", dest_start)
                if end < 0:
                    continue
                dest_end = end
            else:
                dest_start = pos
                dest_end = pos
                while dest_end < len(line) and line[dest_end] not in " \t":
                    dest_end += 1
            dest = line[dest_start:dest_end]
            if dest:
                result.setdefault(dest, []).append((body_line, dest_start, dest_end))
        return result

    def _backfill_reference_spans(self) -> None:
        """Populate dest spans on reference links from their definitions."""
        ref_defs = self._ref_def_dest_spans()
        for link in self._links:
            if not link.is_reference or link.has_dest_span:
                continue
            entries = ref_defs.get(link.href)
            if not entries:
                continue
            # Unambiguous: exactly one definition with this destination.
            # With multiple defs sharing a destination we can't determine
            # which label this link used, so we skip (safe degradation).
            if len(entries) == 1:
                body_line, col_start, col_end = entries[0]
                link.dest_body_line = body_line
                link.dest_file_line = self.file_line(body_line)
                link.dest_col_start = col_start
                link.dest_col_end = col_end

    def _ensure_walked(self) -> None:
        if self._walked:
            return
        self._walked = True
        for token in self._tokens:
            if token.type != "inline":
                continue
            walker = _InlineWalker(self, token)
            walker.walk(token.children)
            self._links.extend(walker.links)
            self._code_spans.extend(walker.code_spans)
            self._segments.extend(walker.segments)
            self._inline_comments.extend(walker.html_comments)
            map_start = token.map[0] if token.map else 0
            for span in walker.verbatim_spans:
                self._inline_maps.append((map_start, token.content, [span]))
        self._backfill_reference_spans()

    # -- accessors ------------------------------------------------------------

    def links(self) -> List[MarkdownLink]:
        """Inline links, images, autolinks, and resolved reference links."""
        self._ensure_walked()
        return list(self._links)

    def code_spans(self) -> List[MarkdownCodeSpan]:
        """Inline code spans, with spans including the backtick delimiters."""
        self._ensure_walked()
        return list(self._code_spans)

    def text_segments(self) -> List[MarkdownTextSegment]:
        """Plain-text token runs — the only scanning surface for path-like detection."""
        self._ensure_walked()
        return list(self._segments)

    def fences(self) -> List[MarkdownFence]:
        """Fenced and indented code blocks (line ranges include delimiters)."""
        result: List[MarkdownFence] = []
        for token in self._tokens:
            if token.type in ("fence", "code_block") and token.map:
                start, end = token.map
                result.append(
                    MarkdownFence(
                        info=(token.info or "").strip(),
                        body_line_start=start + 1,
                        body_line_end=end,
                        file_line_start=self.file_line(start + 1),
                        file_line_end=self.file_line(end),
                        indented=token.type == "code_block",
                        markup=token.markup or "",
                        nested=token.level > 0,
                    )
                )
        return result

    def headings(self) -> List[MarkdownHeading]:
        """ATX and setext headings."""
        result: List[MarkdownHeading] = []
        tokens = self._tokens
        for i, token in enumerate(tokens):
            if token.type != "heading_open" or not token.map:
                continue
            level = int(token.tag[1]) if len(token.tag) == 2 and token.tag[1].isdigit() else 1
            text = ""
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                text = tokens[i + 1].content.replace("\n", " ")
            result.append(
                MarkdownHeading(
                    level=level,
                    text=text,
                    body_line=token.map[0] + 1,
                    file_line=self.file_line(token.map[0] + 1),
                    body_line_end=token.map[1] + 1,
                    setext=token.markup in ("=", "-"),
                )
            )
        return result

    def html_comments(self) -> List[MarkdownHtmlComment]:
        """HTML comments from block-level HTML and inline HTML."""
        self._ensure_walked()
        result: List[MarkdownHtmlComment] = []
        for token in self._tokens:
            if token.type != "html_block" or not token.map:
                continue
            start_line0 = token.map[0]
            region = "\n".join(self._lines[token.map[0] : token.map[1]])
            for match in _HTML_COMMENT_RE.finditer(region):
                line_delta_start = region.count("\n", 0, match.start())
                line_delta_end = region.count("\n", 0, match.end())
                result.append(
                    MarkdownHtmlComment(
                        text=match.group(1),
                        body_line_start=start_line0 + line_delta_start + 1,
                        body_line_end=start_line0 + line_delta_end + 1,
                        file_line_start=self.file_line(start_line0 + line_delta_start + 1),
                        file_line_end=self.file_line(start_line0 + line_delta_end + 1),
                    )
                )
        result.extend(self._inline_comments)
        result.sort(key=lambda c: c.body_line_start)
        return result

    # -- prose ---------------------------------------------------------------

    def _compute_prose(self) -> List[str]:
        if self._prose is not None:
            return self._prose
        self._ensure_walked()
        lines = list(self._lines)

        # Fenced and indented code blocks: blank the whole lines (delimiters
        # included), matching the legacy strip behaviour.
        for token in self._tokens:
            if token.type in ("fence", "code_block") and token.map:
                for i in range(token.map[0], min(token.map[1], len(lines))):
                    lines[i] = ""

        # HTML comments in block-level HTML: blank with spaces, preserving
        # columns and line count.
        for token in self._tokens:
            if token.type != "html_block" or not token.map:
                continue
            start0, end0 = token.map
            region_lines = lines[start0:end0]
            region = "\n".join(self._lines[start0:end0])
            for match in _HTML_COMMENT_RE.finditer(region):
                self._blank_region(region_lines, region, match.start(), match.end())
            lines[start0:end0] = region_lines

        # Inline verbatim spans (code spans, inline HTML comments): blank
        # with spaces using the column glue.
        for map_start, content, spans in self._inline_maps:
            cmap = _ContentMap(self._lines, map_start, content)
            for span_start, span_end in spans:
                start_line0, start_col = cmap.locate(span_start)
                end_line0, end_col = cmap.locate(span_end)
                if start_col is None or end_col is None:
                    continue
                for line0 in range(start_line0, min(end_line0, len(lines) - 1) + 1):
                    if line0 >= len(lines):
                        break
                    text = lines[line0]
                    begin = start_col if line0 == start_line0 else 0
                    finish = end_col if line0 == end_line0 else len(text)
                    if begin < 0 or begin > len(text) or finish > len(text):
                        continue
                    lines[line0] = text[:begin] + " " * (finish - begin) + text[finish:]

        self._prose = lines
        return lines

    @staticmethod
    def _blank_region(region_lines: List[str], region: str, start: int, end: int) -> None:
        """Blank [start, end) offsets of *region* (joined lines) with spaces."""
        line_idx = region.count("\n", 0, start)
        line_start_offset = region.rfind("\n", 0, start) + 1
        pos = start
        while pos < end and line_idx < len(region_lines):
            line_text = region_lines[line_idx]
            col = pos - line_start_offset
            line_end_offset = line_start_offset + len(line_text)
            chunk_end = min(end, line_end_offset)
            col_end = chunk_end - line_start_offset
            if 0 <= col <= len(line_text) and col_end <= len(line_text):
                region_lines[line_idx] = (
                    line_text[:col] + " " * (col_end - col) + line_text[col_end:]
                )
            pos = line_end_offset + 1  # skip the newline
            line_start_offset = pos
            line_idx += 1

    def prose_lines(self) -> List[Tuple[int, str]]:
        """``(file_line, text)`` pairs with verbatim content blanked.

        Fences and indented code blocks become empty lines; code spans and
        HTML comments are blanked with spaces (columns preserved).  Line
        count always matches the body.
        """
        prose = self._compute_prose()
        return [(self.file_line(i + 1), text) for i, text in enumerate(prose)]

    def prose_text(self) -> str:
        """The prose body as a single string — drop-in replacement for the
        legacy ``read_body(strip_code_blocks=True)`` result."""
        if self._prose_text is None:
            self._prose_text = "\n".join(self._compute_prose())
        return self._prose_text

    # -- code-span helpers -----------------------------------------------------

    def span_is_exact_code_content(
        self, body_line: int, col_start: int, col_end: int
    ) -> Optional[MarkdownCodeSpan]:
        """Return the enclosing code span if [col_start, col_end) is exactly its
        content, else ``None``.

        Ports the legacy ``inline_code_span_bounds`` semantics: a path that is
        the entire content of a code span is still linkable (the fix wraps the
        whole span, backticks included).
        """
        for span in self.code_spans():
            if span.body_line != body_line or span.col_start is None or span.col_end is None:
                continue
            content_start = span.col_start + len(span.markup)
            content_end = span.col_end - len(span.markup)
            # Account for the one-space padding rule.
            raw = self.line(body_line)[content_start:content_end]
            if raw != span.content and raw.strip() == span.content:
                pad = raw.find(span.content)
                content_start += pad
                content_end = content_start + len(span.content)
            if content_start == col_start and content_end == col_end:
                return span
        return None
