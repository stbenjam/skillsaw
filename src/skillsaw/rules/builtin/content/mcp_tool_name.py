"""Content fully-qualified MCP tool name rule"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, FrozenSet, List, Set, Tuple

from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.markdown_doc import MarkdownDoc, file_span, splice
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks
from skillsaw.utils import read_text

# `mcp__<server>__<tool>` is the flattened MCP tool identifier of Claude
# Code and the Claude Agent SDK, and the same convention appears throughout
# OpenAI's Codex plugin content — a client convention, not part of the MCP
# specification.  Keep the pattern anchored on the literal `mcp__` and never
# generalize it to bare `<server>__<tool>`, which would false-positive on
# ordinary dunder-style identifiers.
#
# Match the maximal `mcp__…` identifier run, then split the server from the
# tool in Python.  No negative lookahead trails the quantifier: a failing
# assertion after `[A-Za-z0-9_-]+` would make the engine backtrack into a
# truncated match and the fix would splice a corrupted span (issue #321).
# The leading lookbehind is safe because when it fails the engine advances
# into the token, where the required literal `mcp__` no longer matches — so
# no truncated match exists to splice.
_MCP_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])mcp__[A-Za-z0-9_-]+")
# ToolSearch accepts one whitespace-free ``select:`` expression containing
# comma-separated tool patterns. Protect the complete expression: checking
# only the characters beside each token misses every member after the first.
_TOOLSEARCH_SELECTOR_RE = re.compile(
    r"(?<![A-Za-z0-9_-])select:[A-Za-z0-9_*?-]+" r"(?:,[A-Za-z0-9_*?-]+)*"
)


class ContentMcpToolNameRule(Rule):
    """Detect fully-qualified MCP tool names in portable prose."""

    # SUGGEST, deliberately: the splice is mechanically exact, but whether
    # the strip is an adequate replacement is a judgment call — a generic
    # short name (`create`, `screenshot`) loses its server hint, and prose
    # that must communicate a runtime identifier needs a hand rewrite — so
    # the fix applies only under `skillsaw fix --suggest`.
    autofix_confidence = AutofixConfidence.SUGGEST

    since = "0.20.0"
    repo_types = None
    default_enabled = False

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
        return (
            "Detect fully-qualified MCP tool names in portable prose that should use "
            "the short tool name"
        )

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @staticmethod
    def _short_name(token: str) -> str:
        """Return the short tool name for *token*, or "" when it has none.

        ``mcp__server__tool`` -> ``tool``.  Only the ``mcp__<server>__``
        prefix is stripped — the split is at the *first* ``__`` after the
        server segment, so a tool whose own name contains ``__``
        (``mcp__internal__report__generate``) keeps every segment of its
        name (``report__generate``).  A token with an empty server segment
        (``mcp____tool``), no ``__`` after the server (``mcp__server``), or
        an empty tool segment (``mcp__server__``) is not a tool reference.
        """
        remainder = token[len("mcp__") :]
        sep = remainder.find("__")
        if sep <= 0:
            return ""
        return remainder[sep + len("__") :]

    def _candidates(
        self, doc: MarkdownDoc, allow: FrozenSet[str]
    ) -> List[Tuple[int, int, str, str]]:
        """Collect ordered (body_line, col_start, token, short_name) candidates.

        Scans prose text and inline code spans — deliberately not fences or
        indented code, where a config example legitimately needs the
        fully-qualified name.  Also skipped: link text (rewriting it would
        corrupt the link) and tokens embedded in URLs or paths.
        """
        results: List[Tuple[int, int, str, str]] = []

        def collect(body_line: int, base_col: int, text: str, markup: str = "") -> None:
            if "mcp__" not in text:
                return
            raw_line = doc.line(body_line)
            selector_spans = [
                (match.start(), match.end()) for match in _TOOLSEARCH_SELECTOR_RE.finditer(text)
            ]
            selector_index = 0
            for match in _MCP_TOKEN_RE.finditer(text):
                while (
                    selector_index < len(selector_spans)
                    and selector_spans[selector_index][1] <= match.start()
                ):
                    selector_index += 1
                if (
                    selector_index < len(selector_spans)
                    and selector_spans[selector_index][0]
                    <= match.start()
                    < selector_spans[selector_index][1]
                ):
                    continue
                token = match.group(0)
                if token in allow:
                    continue
                short = self._short_name(token)
                if not short:
                    continue
                col = base_col + match.start()
                # A token embedded in a URL or path must keep its exact
                # spelling, so reject a match preceded by a path separator
                # or dot (https://…/mcp__jira__getIssue, C:\tools\…), one
                # whose whitespace-delimited chunk carries a URL scheme
                # (query and fragment positions), or one followed by a
                # filename extension (mcp__jira__getIssue.json).  Every
                # check reads characters adjacent to the complete match in
                # code, never as a lookaround on the quantifier (issue
                # #321).
                before = raw_line[:col]
                adjacent_before = before
                if markup and not text[: match.start()].strip():
                    adjacent_before = raw_line[: base_col - len(markup)]
                after = raw_line[col + len(token) :]
                adjacent_after = after
                if markup and not text[match.end() :].strip():
                    closing_markup = base_col + len(text)
                    adjacent_after = raw_line[closing_markup + len(markup) :]

                if adjacent_before and adjacent_before[-1] in "/.\\":
                    continue
                chunk_start = max(before.rfind(" "), before.rfind("\t")) + 1
                if "://" in before[chunk_start:]:
                    continue
                paired_emphasis = (
                    not markup and adjacent_before.endswith("*") and adjacent_after.startswith("*")
                )
                if adjacent_before.endswith(("]", "}")) or (
                    adjacent_before.endswith(("*", "?")) and not paired_emphasis
                ):
                    continue
                if adjacent_after.startswith(("/", "\\", "[", "{")):
                    continue
                if adjacent_after.startswith(("@(", "+(", "!(", "?(", "*(")):
                    continue
                if adjacent_after.startswith("*") and not paired_emphasis:
                    continue
                if markup and match.end() < len(text) and after.startswith("?"):
                    continue
                if adjacent_after[:1] == "." and adjacent_after[1:2].isalnum():
                    continue
                results.append((body_line, col, token, short))

        for seg in doc.text_segments():
            if seg.in_link or seg.col_start is None:
                continue
            collect(seg.body_line, seg.col_start, seg.text)

        for span in doc.code_spans():
            if span.in_link or span.multiline or span.col_start is None or span.col_end is None:
                continue
            # col_start/col_end include the backtick markup; scan the raw
            # source between the backticks so columns stay exact even when
            # CommonMark stripped padding spaces from span.content.
            inner_start = span.col_start + len(span.markup)
            inner_end = span.col_end - len(span.markup)
            raw_inner = doc.line(span.body_line)[inner_start:inner_end]
            collect(span.body_line, inner_start, raw_inner, span.markup)

        results.sort(key=lambda r: (r[0], r[1]))
        return results

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        # Config validation checks only that `allow` is a list; a non-string
        # entry must not crash the rule, so filter rather than hash it.
        allow = frozenset(x for x in self.setting("allow") if isinstance(x, str))
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=False)
            if not body or "mcp__" not in body:
                continue
            candidates = self._candidates(cf.markdown, allow)
            if not candidates:
                continue
            # A fix is only advertised when the candidate's span verifies in
            # the enclosing file.  ``diagnostic_only`` bodies (decoded out of
            # a non-markdown host such as a JSON string) never splice; other
            # hosts can defeat splicing per candidate — a folded YAML scalar
            # (``>``) reflows body lines, so ``file_span()`` cannot locate
            # the text and ``fix()`` would silently drop the edit.
            content = None if cf.diagnostic_only else read_text(cf.path)
            doc = cf.markdown
            occurrences: Dict[Tuple[int, str], int] = {}
            for body_line, col, token, short in candidates:
                ordinal = occurrences.get((body_line, token), 0)
                occurrences[(body_line, token)] = ordinal + 1
                # A server may expose a short name that itself looks qualified.
                # Another fix pass would then strip part of the actual tool name.
                ambiguous_short = short.startswith("mcp__") and bool(self._short_name(short))
                fixable = (
                    not ambiguous_short
                    and content is not None
                    and file_span(
                        doc, content, doc.file_line(body_line), body_line, col, col + len(token)
                    )
                    is not None
                )
                prefix = token[: len(token) - len(short)]
                violations.append(
                    self.violation(
                        f"Fully-qualified MCP tool name '{token}' — use the short name "
                        f"'{short}' (the {prefix} prefix depends on the reader's server name)",
                        block=cf,
                        line=body_line,
                        fixable=fixable,
                        fingerprint_discriminator=f"{token}:{ordinal}",
                    )
                )
        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation], **kwargs: object
    ) -> List[AutofixResult]:
        # Config validation checks only that `allow` is a list; a non-string
        # entry must not crash the rule, so filter rather than hash it.
        allow = frozenset(x for x in self.setting("allow") if isinstance(x, str))
        fixes_by_file: Dict[Path, List[Tuple[str, int, RuleViolation]]] = defaultdict(list)
        for v in violations:
            if not v.file_path or v.block is None or not v.fixable:
                continue
            # The fingerprint discriminator carries the fix target —
            # token:ordinal, set by check() — so the human-readable message
            # is never load-bearing for a file-mutating path.
            token, _, tail = (v.fingerprint_discriminator or "").rpartition(":")
            if not token or not tail.isdigit():
                continue
            fixes_by_file[v.file_path].append((token, int(tail), v))

        results: List[AutofixResult] = []
        for fpath, replacements in fixes_by_file.items():
            # Read through utils.read_text so the splice source shares the
            # MarkdownDoc coordinate system: both are BOM-stripped and
            # LF-normalized.
            content = read_text(fpath)
            if content is None:
                continue
            edits: List[Tuple[int, int, int, str]] = []
            violations_fixed: List[RuleViolation] = []
            used_spans: Set[Tuple[int, int, int]] = set()
            # One candidate scan per block: text_segments() and code_spans()
            # each return a fresh list copy per call.
            candidates_by_block: Dict[int, List[Tuple[int, int, str, str]]] = {}
            for token, ordinal, v in replacements:
                doc = v.block.markdown
                candidates = candidates_by_block.get(id(v.block))
                if candidates is None:
                    candidates = self._candidates(doc, allow)
                    candidates_by_block[id(v.block)] = candidates
                # Select the occurrence the violation reports, so a partial
                # violation set — a baseline suppressing one ordinal — never
                # rewrites an earlier suppressed occurrence in its place.
                occurrence = -1
                for body_line, col, candidate, short in candidates:
                    if candidate != token:
                        continue
                    file_line = doc.file_line(body_line)
                    if file_line != v.file_line:
                        continue
                    occurrence += 1
                    if occurrence != ordinal:
                        continue
                    located = file_span(doc, content, file_line, body_line, col, col + len(token))
                    if located is None:
                        break
                    key = (file_line, located[0], located[1])
                    if key in used_spans:
                        break
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
                        confidence=AutofixConfidence.SUGGEST,
                        original_content=content,
                        fixed_content=fixed,
                        description=f"Strip the mcp__ prefix from {len(violations_fixed)} MCP tool name(s)",
                        violations_fixed=violations_fixed,
                    )
                )
        return results
