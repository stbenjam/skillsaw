"""Content fully-qualified MCP tool name rule"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.markdown_doc import MarkdownDoc, file_span, splice
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks
from skillsaw.utils import read_text

# Match the maximal `mcp__…` identifier run, then split the server from the
# tool in Python.  No negative lookahead trails the quantifier: a failing
# assertion after `[A-Za-z0-9_-]+` would make the engine backtrack into a
# truncated match and the fix would splice a corrupted span (issue #321).
# The leading lookbehind is a fixed-width character class, not an assertion
# wrapped around a quantifier, so it cannot induce that retry either.
_MCP_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])mcp__[A-Za-z0-9_-]+")


class ContentMcpToolNameRule(Rule):
    """Detect fully-qualified MCP tool names in prose"""

    autofix_confidence = AutofixConfidence.SAFE

    formats = None
    since = "0.20.0"
    repo_types = None

    config_schema = {
        "allow": {
            "type": "list",
            "default": [],
            "description": "Fully-qualified MCP tool names to leave unflagged",
        },
    }

    @property
    def rule_id(self) -> str:
        return "content-mcp-tool-name"

    @property
    def description(self) -> str:
        return "Detect fully-qualified MCP tool names that should use the short tool name"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @staticmethod
    def _short_name(token: str) -> str:
        """Return the short tool name for *token*, or "" when it has none.

        ``mcp__server__tool`` -> ``tool``.  A token with no ``__`` after the
        server segment (``mcp__server``) or an empty tool segment
        (``mcp__server__``) has no short name and is not a tool reference.
        Known limitation: a tool whose own name contains ``__`` resolves to
        its last segment; use the ``allow`` option for those.
        """
        remainder = token[len("mcp__") :]
        sep = remainder.rfind("__")
        if sep < 0:
            return ""
        return remainder[sep + len("__") :]

    def _candidates(self, doc: MarkdownDoc, allow: List[str]) -> List[Tuple[int, int, str, str]]:
        """Collect ordered (body_line, col_start, token, short_name) candidates.

        Scans prose text and inline code spans — deliberately not fences or
        indented code, where a config example legitimately needs the
        fully-qualified name.
        """
        results: List[Tuple[int, int, str, str]] = []

        def collect(body_line: int, base_col: int, text: str) -> None:
            for match in _MCP_TOKEN_RE.finditer(text):
                token = match.group(0)
                if token in allow:
                    continue
                short = self._short_name(token)
                if not short:
                    continue
                results.append((body_line, base_col + match.start(), token, short))

        for seg in doc.text_segments():
            if seg.col_start is None:
                continue
            collect(seg.body_line, seg.col_start, seg.text)

        for span in doc.code_spans():
            if span.multiline or span.col_start is None or span.col_end is None:
                continue
            # col_start/col_end include the backtick markup; scan the raw
            # source between the backticks so columns stay exact even when
            # CommonMark stripped padding spaces from span.content.
            inner_start = span.col_start + len(span.markup)
            inner_end = span.col_end - len(span.markup)
            raw_inner = doc.line(span.body_line)[inner_start:inner_end]
            collect(span.body_line, inner_start, raw_inner)

        results.sort(key=lambda r: (r[0], r[1]))
        return results

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        allow = self.setting("allow")
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            # A body extracted from a non-markdown host has no span in the
            # enclosing file to splice into, so fix() always skips it.
            fixable = not cf.diagnostic_only
            for body_line, _col, token, short in self._candidates(cf.markdown, allow):
                prefix = token[: len(token) - len(short)]
                violations.append(
                    self.violation(
                        f"Fully-qualified MCP tool name '{token}' — use the short name "
                        f"'{short}' (the {prefix} prefix depends on the reader's server name)",
                        block=cf,
                        line=body_line,
                        fixable=fixable,
                    )
                )
        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation], **kwargs: object
    ) -> List[AutofixResult]:
        allow = self.setting("allow")
        fixes_by_file: Dict[Path, List[Tuple[str, RuleViolation]]] = defaultdict(list)
        for v in violations:
            if not v.file_path or v.block is None or not v.fixable:
                continue
            fixes_by_file[v.file_path].append((v.message.split("'")[1], v))

        results: List[AutofixResult] = []
        for fpath, replacements in fixes_by_file.items():
            # Read through utils.read_text so the splice source shares the
            # MarkdownDoc coordinate system: both are BOM-stripped and
            # LF-normalized.
            content = read_text(fpath)
            if content is None:
                continue
            edits = []
            violations_fixed = []
            used_spans = set()
            for token, v in replacements:
                doc = v.block.markdown
                for body_line, col, candidate, short in self._candidates(doc, allow):
                    if candidate != token:
                        continue
                    file_line = doc.file_line(body_line)
                    if file_line != v.file_line:
                        continue
                    located = file_span(doc, content, file_line, body_line, col, col + len(token))
                    if located is None:
                        continue
                    key = (file_line, located[0], located[1])
                    if key in used_spans:
                        continue
                    used_spans.add(key)
                    edits.append((file_line, located[0], located[1], short))
                    violations_fixed.append(v)
                    break
            fixed = splice(content, edits)
            if fixed != content:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=fpath,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed,
                        description=f"Strip the mcp__ prefix from {len(violations_fixed)} MCP tool name(s)",
                        violations_fixed=violations_fixed,
                    )
                )
        return results
