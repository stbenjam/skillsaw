"""Content unlinked internal reference rule"""

import re
from collections import defaultdict
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Tuple

from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.markdown_doc import MarkdownCodeSpan, MarkdownDoc, file_span, splice
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
)

_IMPORT_LINE_RE = re.compile(r"^\s*@\S")


class ContentUnlinkedInternalReferenceRule(Rule):
    """Detect bare path-like strings that are not wrapped in markdown link syntax"""

    autofix_confidence = AutofixConfidence.SAFE

    formats = None
    since = "0.9.0"
    repo_types = None

    config_schema = {
        "patterns": {
            "type": "list",
            "default": ["./**/*.*", "references/**/*.md"],
            "description": "Glob patterns for path-like strings to flag when unlinked",
        },
    }

    # Match path-like strings: contain / and a file extension, or start with ./
    _PATH_LIKE_RE = re.compile(
        r"(?<!\()"  # not preceded by ( (would be inside link syntax)
        r"(?:"
        r"\./[\w./_-]+"  # starts with ./
        r"|"
        r"[\w._-]+(?:/[\w._-]+)+\.[\w]{1,10}"  # contains / and has extension
        r")"
        r"(?!\))"  # not followed by ) (would be inside link syntax)
    )

    # Detect URLs so we can skip path-like fragments inside them
    _URL_RE = re.compile(r"https?://[^\s)]+")

    @property
    def rule_id(self) -> str:
        return "content-unlinked-internal-reference"

    @property
    def description(self) -> str:
        return "Detect bare path-like strings not wrapped in markdown link syntax"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def _is_inside_url(self, text: str, match_start: int, match_end: int) -> bool:
        """Check if a match position falls inside a URL."""
        for url_match in self._URL_RE.finditer(text):
            if url_match.start() <= match_start and match_end <= url_match.end():
                return True
        return False

    def _code_span_is_exact_path(self, doc: MarkdownDoc, span: MarkdownCodeSpan) -> bool:
        """True when the code span's source content is exactly a path-like string.

        A code span whose entire content is a path (no padding, no extra text
        like a variable prefix) is still a linkable reference; anything else
        is code and must not be flagged.
        """
        match = self._PATH_LIKE_RE.fullmatch(span.content)
        if not match:
            return False
        if span.col_start is None or span.col_end is None:
            return False
        raw_inner = doc.line(span.body_line)[
            span.col_start + len(span.markup) : span.col_end - len(span.markup)
        ]
        return raw_inner == span.content

    def _candidates(
        self, doc: MarkdownDoc, patterns: List[str]
    ) -> List[Tuple[int, Optional[int], str, Optional[MarkdownCodeSpan]]]:
        """Collect (body_line, col_start, path_str, code_span) candidates in order."""
        results: List[Tuple[int, Optional[int], str, Optional[MarkdownCodeSpan]]] = []
        for seg in doc.text_segments():
            if seg.in_link:
                continue
            if _IMPORT_LINE_RE.match(doc.line(seg.body_line)):
                continue
            for match in self._PATH_LIKE_RE.finditer(seg.text):
                path_str = match.group(0)
                if self._is_inside_url(seg.text, match.start(), match.end()):
                    continue
                if not any(PurePath(path_str).match(p) for p in patterns):
                    continue
                col = seg.col_start + match.start() if seg.col_start is not None else None
                results.append((seg.body_line, col, path_str, None))
        for span in doc.code_spans():
            if span.in_link:
                continue
            if _IMPORT_LINE_RE.match(doc.line(span.body_line)):
                continue
            if not self._code_span_is_exact_path(doc, span):
                continue
            if not any(PurePath(span.content).match(p) for p in patterns):
                continue
            results.append((span.body_line, span.col_start, span.content, span))
        results.sort(key=lambda r: (r[0], r[1] if r[1] is not None else 0))
        return results

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        root = context.root_path.resolve()
        patterns = self.config.get("patterns", self.config_schema["patterns"]["default"])
        violations = []
        for cf in gather_all_content_blocks(context):
            doc = cf.markdown
            for body_line, _col, path_str, _span in self._candidates(doc, patterns):
                resolved = (cf.path.parent / path_str).resolve()
                file_exists = False
                try:
                    resolved.relative_to(root)
                    file_exists = resolved.exists()
                except ValueError:
                    pass
                msg = f"Unlinked path reference: '{path_str}' — consider wrapping in link syntax [{path_str}]({path_str})"
                if file_exists:
                    msg += " (file exists, autofixable)"
                violations.append(self.violation(msg, block=cf, line=body_line))
        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation], **kwargs: object
    ) -> List[AutofixResult]:
        patterns = self.config.get("patterns", self.config_schema["patterns"]["default"])
        fixes_by_file: Dict[Path, List[tuple]] = defaultdict(list)
        for v in violations:
            if not v.file_path or "autofixable" not in v.message or v.block is None:
                continue
            path_str = v.message.split("'")[1]
            fixes_by_file[v.file_path].append((path_str, v))

        results: List[AutofixResult] = []
        for fpath, replacements in fixes_by_file.items():
            try:
                content = fpath.read_text(encoding="utf-8")
            except OSError:
                continue
            edits = []
            violations_fixed = []
            used_spans = set()
            for path_str, v in replacements:
                doc = v.block.markdown
                edit = None
                for body_line, col, candidate, span in self._candidates(doc, patterns):
                    if candidate != path_str or col is None:
                        continue
                    file_line = doc.file_line(body_line)
                    if file_line != v.file_line:
                        continue
                    if span is not None:
                        col_end = span.col_end
                        bt = span.markup
                        replacement = f"[{bt}{path_str}{bt}]({path_str})"
                    else:
                        col_end = col + len(path_str)
                        replacement = f"[{path_str}]({path_str})"
                    located = file_span(doc, content, file_line, body_line, col, col_end)
                    if located is None:
                        continue
                    key = (file_line, located[0], located[1])
                    if key in used_spans:
                        continue
                    edit = (file_line, located[0], located[1], replacement)
                    used_spans.add(key)
                    break
                if edit is not None:
                    edits.append(edit)
                    violations_fixed.append(v)
            fixed = splice(content, edits)
            if fixed != content:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=fpath,
                        confidence=AutofixConfidence.SAFE,
                        original_content=content,
                        fixed_content=fixed,
                        description=f"Wrap {len(violations_fixed)} bare path(s) in markdown link syntax",
                        violations_fixed=violations_fixed,
                    )
                )
        return results
