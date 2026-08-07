"""Content inline tool examples rule"""

import re
from typing import Any, Dict, List, Optional, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.blocks import ContentBlock
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks

# A line that begins a call-syntax invocation: an optional shell prompt,
# declaration keyword (const/let/var), assignment, and/or `await`
# (before or after the assignment), then a dotted identifier and an
# opening paren.  Continuation lines of a multi-line call are tracked
# by paren depth in _fence_callee().
_CALL_HEAD_RE = re.compile(
    r"^(?:\$\s+)?(?:await\s+)?(?:(?:const|let|var)\s+)?"
    r"(?:[\w.]+(?:\s*:\s*[\w.\[\], ]+)?\s*=\s*)?(?:await\s+)?"
    r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\("
)

# Control-flow and I/O keywords that take parens in common languages —
# `if (x) {` or `while (true)` is code structure, not a tool invocation.
# Applied to bare names only: `client.print(...)` is a namespaced tool.
_NON_TOOL_CALLEES = frozenset(
    {
        "if",
        "elif",
        "else",
        "for",
        "while",
        "switch",
        "catch",
        "except",
        "return",
        "assert",
        "await",
        "with",
        "def",
        "function",
        "print",
        "println",
    }
)

# Comment syntax by fence language: '#' opens a comment in Python or
# shell but '//' is floor division in Python; the reverse holds for
# C-family languages.  An unlabeled fence accepts both styles.
_HASH_COMMENT_LANGS = frozenset({"python", "py", "python3", "sh", "bash", "shell", "zsh", "yaml"})
_SLASH_COMMENT_LANGS = frozenset(
    {"js", "javascript", "ts", "typescript", "jsx", "tsx", "java", "c", "cpp", "go", "rust"}
)
_ALL_COMMENT_STYLES = frozenset({"#", "//"})

# Keywords that may directly precede a parenthesized expression inside
# call arguments without invoking anything ('x for x in items if
# (x.ready)') — a '(' after one of these is grouping, not a second call.
_NON_CALL_KEYWORDS = frozenset(
    {
        "if",
        "elif",
        "else",
        "for",
        "while",
        "in",
        "not",
        "and",
        "or",
        "return",
        "await",
        "yield",
        "lambda",
        "assert",
        "match",
        "case",
        "switch",
        "catch",
        "typeof",
        "del",
        "raise",
        "throw",
        "new",
    }
)

_INDENTED_PREFIX_RE = re.compile(r"^(?:    |\t)")

# Container prefix a nested fence carries on every line: blockquote
# markers and/or list-item indentation.  Measured on the opening fence
# line and stripped from the content so call heads sit at column 0.
_CONTAINER_PREFIX_RE = re.compile(r"^\s*(?:>\s*)*")

# Blockquote markers alone — used per line where trailing whitespace is
# code indentation that must survive (indented blocks in blockquotes).
_QUOTE_MARKER_RE = re.compile(r"^(?:\s*>)+\s?")

# One blockquote level, for peeling container markers a level at a time
# so a literal '>' in the code itself survives.  A container marker may
# be indented at most three spaces (CommonMark) — a '>' after a 4-space
# code indent ('>     > search(...)') is payload, never a container.
_QUOTE_LEAD_RE = re.compile(r"^ {0,3}>")
_ONE_QUOTE_LEVEL_RE = re.compile(r"^ {0,3}>\s?")


class ContentInlineToolExamplesRule(Rule):
    """Detect consecutive fenced examples that all invoke the same tool"""

    formats = None
    repo_types = None  # instruction content appears in every repo type
    default_enabled = False
    since = "0.19.0"

    _DEFAULT_MIN_CONSECUTIVE = 3
    _DEFAULT_MAX_LINES_BETWEEN = 2

    config_schema = {
        "min-consecutive": {
            "type": "int",
            "default": _DEFAULT_MIN_CONSECUTIVE,
            "description": (
                "Minimum number of consecutive fenced blocks invoking the "
                "same tool or function before the run is flagged"
            ),
        },
        "max-lines-between": {
            "type": "int",
            "default": _DEFAULT_MAX_LINES_BETWEEN,
            "description": (
                "Maximum number of non-blank prose lines allowed between two "
                "adjacent fenced blocks (caption lines like 'Another "
                "example:') before the run is considered broken; a heading "
                "always breaks the run, and HTML comments are not counted"
            ),
        },
    }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        min_consecutive = self.config.get("min-consecutive", self._DEFAULT_MIN_CONSECUTIVE)
        if not isinstance(min_consecutive, int) or isinstance(min_consecutive, bool):
            raise ValueError(
                f"'min-consecutive' for rule '{self.rule_id}' must be an "
                f"integer, got {type(min_consecutive).__name__}"
            )
        if min_consecutive < 2:
            raise ValueError(
                f"'min-consecutive' for rule '{self.rule_id}' must be at "
                f"least 2, got {min_consecutive}"
            )
        self._min_consecutive = min_consecutive

        max_between = self.config.get("max-lines-between", self._DEFAULT_MAX_LINES_BETWEEN)
        if not isinstance(max_between, int) or isinstance(max_between, bool):
            raise ValueError(
                f"'max-lines-between' for rule '{self.rule_id}' must be an "
                f"integer, got {type(max_between).__name__}"
            )
        if max_between < 0:
            raise ValueError(
                f"'max-lines-between' for rule '{self.rule_id}' must be at "
                f"least 0, got {max_between}"
            )
        self._max_between = max_between

    @property
    def rule_id(self) -> str:
        return "content-inline-tool-examples"

    @property
    def description(self) -> str:
        return "Detect consecutive fenced examples that all invoke the same tool"

    def default_severity(self) -> Severity:
        return Severity.INFO

    @staticmethod
    def _strip_comment_pieces(line: str, closes_earlier: bool) -> str:
        """Remove HTML-comment pieces from one comment-boundary line.

        The line comes from an AST-located comment span, so this is
        visibility accounting for prose counting, not HTML sanitization.
        Only when the AST says this line closes a comment opened on an
        earlier line (*closes_earlier*) is the text up to the first
        ``-->`` dropped — a literal ``-->`` in prose ('Caption --> next')
        is visible text, not a closer.  Complete inline spans and a
        dangling opener are then removed; what survives is the line's
        visible prose.
        """
        if closes_earlier:
            close = line.find("-->")
            if close != -1:
                line = line[close + 3 :]
        # Single pass over the line — appending visible segments keeps
        # this linear even on a crafted line packed with comment spans.
        parts = []
        i = 0
        while True:
            start = line.find("<!--", i)
            if start == -1:
                parts.append(line[i:])
                break
            parts.append(line[i:start])
            end = line.find("-->", start + 4)
            if end == -1:
                break
            i = end + 3
        return "".join(parts)

    @staticmethod
    def _is_closing_marker(line: str, markup: str) -> bool:
        """True when *line* is the fence's closing delimiter run."""
        stripped = _QUOTE_MARKER_RE.sub("", line).strip()
        return (
            bool(markup)
            and bool(stripped)
            and set(stripped) == {markup[0]}
            and len(stripped) >= len(markup)
        )

    @staticmethod
    def _dedent(raw: List[str]) -> List[str]:
        """Strip the common leading whitespace of the non-blank lines.

        Unlike a fixed 4-space strip this normalizes indented blocks at
        any nesting depth (a list-nested indented block sits 6+ columns
        deep) while preserving the relative indent of continuation lines.
        """
        indents = [len(line) - len(line.lstrip()) for line in raw if line.strip()]
        if not indents:
            return raw
        cut = min(indents)
        return [line[cut:] if line.strip() else line for line in raw]

    @staticmethod
    def _fence_content_lines(fence, lines: List[str]) -> List[str]:
        """The code lines of *fence*, with delimiters and container/indent
        prefixes removed so call heads sit at column 0.

        ``body_line_start``/``body_line_end`` are 1-based and include the
        fence delimiters for fenced blocks; indented blocks have no
        delimiters and carry blockquote markers and/or their code indent
        on every line.  Container-nested content (blockquote markers,
        list-item indentation — including a fence opened on the list
        marker line itself) is normalized by stripping quote markers and
        the common indent; a fence outside any container is only
        dedented (CommonMark allows up to three spaces of indentation),
        so code that legitimately starts with ``>`` survives.
        """
        if fence.indented:
            raw = lines[fence.body_line_start - 1 : fence.body_line_end]
            # Only a container-nested block carries quote markers; on a
            # top-level indented block a leading '>' is literal code
            # (quoted output samples) and must survive.
            if fence.nested:
                raw = ContentInlineToolExamplesRule._strip_common_quote_levels(raw)
            return ContentInlineToolExamplesRule._dedent(raw)
        # An unclosed fence at end of file has no closing delimiter —
        # its final line is content and must not be sliced off.
        end0 = fence.body_line_end - 1
        last = lines[end0] if 0 <= end0 < len(lines) else ""
        if ContentInlineToolExamplesRule._is_closing_marker(last, fence.markup):
            raw = lines[fence.body_line_start : end0]
        else:
            raw = lines[fence.body_line_start : end0 + 1]
        if fence.nested:
            # Peel exactly the container's quote depth, measured on the
            # opening delimiter line, one marker at a time per line —
            # CommonMark lets the space after '>' vary line to line
            # ('> ```' with '>search(...)' content), so an exact-prefix
            # match would miss legal lines, while a blanket sub would
            # also eat a literal '>' belonging to the code
            # ('> > search(...)').
            opening = lines[fence.body_line_start - 1] if fence.body_line_start >= 1 else ""
            depth = _CONTAINER_PREFIX_RE.match(opening).group(0).count(">")
            for _ in range(depth):
                raw = [
                    _ONE_QUOTE_LEVEL_RE.sub("", line, count=1) if line.strip() else line
                    for line in raw
                ]
        # Dedent even outside containers: CommonMark allows a top-level
        # fence (and its content) to be indented up to three spaces.
        return ContentInlineToolExamplesRule._dedent(raw)

    @staticmethod
    def _strip_common_quote_levels(raw: List[str]) -> List[str]:
        """Peel blockquote-marker levels shared by every non-blank line.

        An indented block has no delimiter line to measure a container
        prefix from, so the container is whatever marker depth is common
        to all lines — a literal ``>`` carried by only some code lines
        survives.
        """
        while True:
            non_blank = [line for line in raw if line.strip()]
            if not non_blank or not all(_QUOTE_LEAD_RE.match(line) for line in non_blank):
                return raw
            raw = [
                _ONE_QUOTE_LEVEL_RE.sub("", line, count=1) if line.strip() else line for line in raw
            ]

    @staticmethod
    def _comment_styles(info: str) -> frozenset:
        """Comment prefixes valid for the fence's declared language.

        ``//`` is floor division in Python, and ``#`` is not a comment
        in C-family languages — a declared language narrows which
        prefixes end call scanning; an unlabeled fence accepts both.
        """
        token = (info or "").strip().split()
        lang = token[0].lower() if token else ""
        if lang in _HASH_COMMENT_LANGS:
            return frozenset({"#"})
        if lang in _SLASH_COMMENT_LANGS:
            return frozenset({"//"})
        return _ALL_COMMENT_STYLES

    @staticmethod
    def _is_comment_line(line: str, styles: frozenset) -> bool:
        return line.lstrip().startswith(tuple(styles))

    @staticmethod
    def _advance(
        line: str, start: int, depth: int, quote: Optional[str], styles: frozenset
    ) -> Tuple[int, Optional[str], Optional[str], bool]:
        """Track paren depth and quote state across ``line[start:]``.

        Parens inside string literals are data, not syntax —
        ``search(query="foo)")`` must not close early.  Returns
        ``(depth, quote, trailer, nested_call)`` where *trailer* is the
        text after the paren that closed the call (``None`` while it
        stays open) and *nested_call* reports an identifier-adjacent
        ``(`` inside the arguments — ``retry(search(...))`` invokes two
        functions, which the rule's single-callee contract excludes.
        """
        nested_call = False
        i = start
        length = len(line)
        while i < length:
            char = line[i]
            if quote:
                if char == "\\":
                    i += 2
                    continue
                if char == quote:
                    quote = None
            elif (char == "#" and "#" in styles) or (
                char == "/" and "//" in styles and i + 1 < length and line[i + 1] == "/"
            ):
                # An inline comment outside any string: the rest of the
                # line is commentary, not call syntax.
                break
            elif char in "\"'`":
                quote = char
            elif char == "(":
                if depth > 0:
                    j = i - 1
                    while j >= 0 and line[j].isspace():
                        j -= 1
                    # An identifier, a closing subscript ('handlers[0](')
                    # or a closing call ('f(x)(') before '(' invokes a
                    # second callable — unless the identifier is a
                    # control keyword grouping an expression
                    # ('... if (x.ready)'), which calls nothing.
                    if j >= 0 and (line[j].isalnum() or line[j] in "_])"):
                        k = j
                        while k >= 0 and (line[k].isalnum() or line[k] == "_"):
                            k -= 1
                        if line[k + 1 : j + 1] not in _NON_CALL_KEYWORDS:
                            nested_call = True
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return 0, None, line[i + 1 :], nested_call
            i += 1
        return depth, quote, None, nested_call

    @staticmethod
    def _is_call_trailer(trailer: str, styles: frozenset) -> bool:
        """True when *trailer* may follow a closed call: nothing, a lone
        statement terminator, and/or a comment in the fence's styles."""
        trailer = trailer.strip()
        if trailer.startswith(";"):
            trailer = trailer[1:].strip()
        return trailer == "" or trailer.startswith(tuple(styles))

    @classmethod
    def _fence_callee(cls, content_lines: List[str], styles: frozenset) -> Optional[str]:
        """The single tool/function every invocation in the fence targets.

        Returns ``None`` unless the fence consists solely of call-syntax
        invocations of one callee (plus their continuation lines and
        comment lines) — mixed callees, statements trailing a call on the
        same or a following line, and ordinary code (imports, control
        flow, prose) disqualify the fence.  The keyword exclusion applies
        to bare names only: ``print(...)`` is code, ``client.print(...)``
        is a namespaced tool.
        """
        callee: Optional[str] = None
        depth = 0
        quote: Optional[str] = None
        for line in content_lines:
            if not line.strip():
                continue
            if depth > 0:
                # A comment-only line inside a multi-line call is
                # commentary, not call state — its text must not open
                # calls or close parens.  Only lines outside strings can
                # be comments.
                if quote is None and cls._is_comment_line(line, styles):
                    continue
                depth, quote, trailer, nested_call = cls._advance(line, 0, depth, quote, styles)
                if nested_call or (
                    trailer is not None and not cls._is_call_trailer(trailer, styles)
                ):
                    return None
                continue
            if cls._is_comment_line(line, styles):
                continue
            match = _CALL_HEAD_RE.match(line)
            if not match:
                return None
            name = match.group(1)
            if "." not in name and (name in _NON_TOOL_CALLEES or name in _NON_CALL_KEYWORDS):
                return None
            if callee is None:
                callee = name
            elif name != callee:
                return None
            depth, quote, trailer, nested_call = cls._advance(
                line, match.end() - 1, 0, None, styles
            )
            if nested_call or (trailer is not None and not cls._is_call_trailer(trailer, styles)):
                return None
        # An invocation left unterminated at the end of the fence
        # ('search(' with no closing paren) is malformed code, not a
        # completed call example.
        if depth > 0 or quote is not None:
            return None
        # A fence that ends mid-call or mid-string is malformed code,
        # not a completed invocation.
        if depth > 0 or quote is not None:
            return None
        return callee

    def _run_breaks(
        self,
        lines: List[str],
        heading_lines: frozenset,
        invisible_lines: frozenset,
        comment_boundary: frozenset,
        closing_boundary: frozenset,
        prev_end: int,
        next_start: int,
    ) -> bool:
        """True when the gap between two fences ends the run.

        *prev_end* / *next_start* are 1-based body lines (closing line of
        the earlier fence, opening line of the later one).  A heading in
        the gap starts a new section — examples across sections are not a
        consecutive run — and more than ``max-lines-between`` non-blank
        lines means the fences are separated by real prose, not captions.
        *heading_lines* holds the AST heading construct lines, so a
        hash-prefixed caption like ``#release-notes`` (not a heading —
        ATX requires a space) counts as prose instead of a break.
        *invisible_lines* — HTML comment interiors and reference
        definitions — are omitted from rendered output and count as
        neither prose nor a break; a comment boundary line that carries
        visible prose alongside the comment markers still counts as
        prose once the comment pieces are stripped.
        """
        non_blank = 0
        for line_num in range(prev_end + 1, next_start):
            if line_num in heading_lines:
                return True
            if line_num in invisible_lines:
                continue
            text = lines[line_num - 1]
            if line_num in comment_boundary:
                text = self._strip_comment_pieces(text, line_num in closing_boundary)
            # A bare '>' between fences in a blockquote is a blank line,
            # not a caption.
            if not _CONTAINER_PREFIX_RE.sub("", text).strip():
                continue
            non_blank += 1
        return non_blank > self._max_between

    def _flush(
        self, cf: ContentBlock, run: List[Tuple[Any, str, tuple]], violations: List[RuleViolation]
    ) -> None:
        if len(run) < self._min_consecutive:
            return
        first_fence, callee, _ = run[0]
        # Non-identical fences may differ in more than their arguments
        # (assignment targets, comments) — claim nothing about how, and
        # call out the one case the scanner can prove: exact repeats.
        distinct = len({key for _, _, key in run})
        qualifier = "" if distinct > 1 else ", each repeating the same invocation,"
        violations.append(
            self.violation(
                f"{len(run)} consecutive fenced examples invoke "
                f"`{callee}`{qualifier} — describe the tool's "
                f"parameters, types, and constraints once instead of "
                f"enumerating example calls",
                block=cf,
                line=first_fence.body_line_start,
            )
        )

    def _check_block(self, cf: ContentBlock) -> List[RuleViolation]:
        fences = sorted(cf.markdown.fences(), key=lambda f: f.body_line_start)
        if len(fences) < self._min_consecutive:
            return []
        body = cf.read_body(strip_code_blocks=False)
        if not body:
            return []
        lines = body.splitlines()
        heading_lines = frozenset(
            line
            for h in cf.markdown.headings()
            for line in range(h.body_line, max(h.body_line_end, h.body_line + 1))
        )
        invisible_lines = set()
        comment_boundary = set()
        closing_boundary = set()
        for c in cf.markdown.html_comments():
            invisible_lines.update(range(c.body_line_start + 1, c.body_line_end))
            comment_boundary.add(c.body_line_start)
            comment_boundary.add(c.body_line_end)
            if c.body_line_end > c.body_line_start:
                closing_boundary.add(c.body_line_end)
        comment_boundary = frozenset(comment_boundary - invisible_lines)
        closing_boundary = frozenset(closing_boundary - invisible_lines)
        # Reference definitions are omitted from rendered output too.
        for r in cf.markdown.reference_definitions():
            invisible_lines.update(range(r.body_line_start, r.body_line_end + 1))
        invisible_lines = frozenset(invisible_lines)
        violations: List[RuleViolation] = []
        run: List[Tuple[Any, str, tuple]] = []
        for fence in fences:
            content_lines = self._fence_content_lines(fence, lines)
            callee = self._fence_callee(content_lines, self._comment_styles(fence.info))
            if callee is None:
                self._flush(cf, run, violations)
                run = []
                continue
            if run:
                prev_fence, prev_callee, _ = run[-1]
                if callee != prev_callee or self._run_breaks(
                    lines,
                    heading_lines,
                    invisible_lines,
                    comment_boundary,
                    closing_boundary,
                    prev_fence.body_line_end,
                    fence.body_line_start,
                ):
                    self._flush(cf, run, violations)
                    run = []
            content_key = tuple(line.strip() for line in content_lines if line.strip())
            run.append((fence, callee, content_key))
        self._flush(cf, run, violations)
        return violations

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            violations.extend(self._check_block(cf))
        return violations
