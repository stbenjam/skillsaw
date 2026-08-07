"""Content inline tool examples rule"""

import re
from typing import Any, Dict, List, Optional, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.blocks import ContentBlock
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks

# A line that begins a call-syntax invocation: an optional shell prompt,
# `await`, or assignment prefix, then a dotted identifier and an opening
# paren.  Anchored per line via MULTILINE by the caller; continuation
# lines of a multi-line call (indented arguments, closing brackets) are
# recognized separately in _fence_callee().
_CALL_HEAD_RE = re.compile(
    r"^(?:\$\s+)?(?:await\s+)?(?:[\w.]+\s*=\s*)?" r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\("
)

# Control-flow and I/O keywords that take parens in common languages —
# `if (x) {` or `while (true)` is code structure, not a tool invocation.
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
        "with",
        "def",
        "function",
        "print",
        "println",
    }
)

# Characters that may open a continuation line of a multi-line call at
# column 0: closing brackets, a comma-separated argument spillover, or a
# comment on the call.
_CONTINUATION_LEAD = ")]}#,"

_INDENTED_PREFIX_RE = re.compile(r"^(?:    |\t)")

# Container prefix a nested fence carries on every line: blockquote
# markers and/or list-item indentation.  Measured on the opening fence
# line and stripped from the content so call heads sit at column 0.
_CONTAINER_PREFIX_RE = re.compile(r"^\s*(?:>\s*)*")


class ContentInlineToolExamplesRule(Rule):
    """Detect runs of fenced examples invoking one tool with varying arguments"""

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
                "always breaks the run"
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
        return "Detect runs of fenced examples invoking one tool with varying arguments"

    def default_severity(self) -> Severity:
        return Severity.INFO

    @staticmethod
    def _fence_content_lines(fence, lines: List[str]) -> List[str]:
        """The code lines of *fence*, with delimiters and indentation removed.

        ``body_line_start``/``body_line_end`` are 1-based and include the
        fence delimiters for fenced blocks; indented blocks have no
        delimiters and carry their 4-space/tab prefix on every line.
        """
        if fence.indented:
            raw = lines[fence.body_line_start - 1 : fence.body_line_end]
            return [_INDENTED_PREFIX_RE.sub("", line) for line in raw]
        raw = lines[fence.body_line_start : fence.body_line_end - 1]
        opening = lines[fence.body_line_start - 1] if fence.body_line_start <= len(lines) else ""
        prefix = _CONTAINER_PREFIX_RE.match(opening).group(0)
        if prefix:
            raw = [line[len(prefix) :] if line.startswith(prefix) else line for line in raw]
        return raw

    @staticmethod
    def _call_consumes_line(line: str, open_idx: int) -> bool:
        """True when the call whose paren opens at *open_idx* spans the line.

        Walks paren depth from the opening paren; once the call closes,
        only a ``;`` or a comment may follow — ``search(a=1); cleanup()``
        is a multi-statement snippet, not a bare invocation.  A call whose
        parens stay open continues on the next line.
        """
        depth = 0
        for i in range(open_idx, len(line)):
            char = line[i]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    trailer = line[i + 1 :].strip()
                    return trailer in ("", ";") or trailer.startswith("#")
        return True

    @staticmethod
    def _fence_callee(content_lines: List[str]) -> Optional[str]:
        """The single tool/function every invocation in the fence targets.

        Returns ``None`` unless the fence consists solely of call-syntax
        invocations of one callee (plus their continuation lines) — mixed
        callees, trailing statements after a call, and ordinary code
        (imports, control flow, prose) disqualify the fence.  The keyword
        exclusion applies to bare names only: ``print(...)`` is code,
        ``client.print(...)`` is a namespaced tool.
        """
        callee: Optional[str] = None
        for line in content_lines:
            if not line.strip():
                continue
            match = _CALL_HEAD_RE.match(line)
            if match:
                name = match.group(1)
                if "." not in name and name in _NON_TOOL_CALLEES:
                    return None
                if not ContentInlineToolExamplesRule._call_consumes_line(line, match.end() - 1):
                    return None
                if callee is None:
                    callee = name
                elif name != callee:
                    return None
                continue
            # Continuation of a multi-line call: an indented argument line
            # or a closing-bracket/comment line.
            if line[0].isspace() or line[0] in _CONTINUATION_LEAD:
                continue
            return None
        return callee

    def _run_breaks(
        self, lines: List[str], heading_lines: frozenset, prev_end: int, next_start: int
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
        """
        non_blank = 0
        for line_num in range(prev_end + 1, next_start):
            if line_num in heading_lines:
                return True
            # A bare '>' between fences in a blockquote is a blank line,
            # not a caption.
            if not _CONTAINER_PREFIX_RE.sub("", lines[line_num - 1]).strip():
                continue
            non_blank += 1
        return non_blank > self._max_between

    def _flush(
        self, cf: ContentBlock, run: List[Tuple[Any, str, tuple]], violations: List[RuleViolation]
    ) -> None:
        if len(run) < self._min_consecutive:
            return
        first_fence, callee, _ = run[0]
        distinct = len({key for _, _, key in run})
        qualifier = (
            "differing only in arguments" if distinct > 1 else "each repeating the same invocation"
        )
        violations.append(
            self.violation(
                f"{len(run)} consecutive fenced examples invoke `{callee}` "
                f"{qualifier} — describe the tool's "
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
        violations: List[RuleViolation] = []
        run: List[Tuple[Any, str, tuple]] = []
        for fence in fences:
            content_lines = self._fence_content_lines(fence, lines)
            callee = self._fence_callee(content_lines)
            if callee is None:
                self._flush(cf, run, violations)
                run = []
                continue
            if run:
                prev_fence, prev_callee, _ = run[-1]
                if callee != prev_callee or self._run_breaks(
                    lines, heading_lines, prev_fence.body_line_end, fence.body_line_start
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
