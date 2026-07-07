"""Content unclosed fence rule"""

from pathlib import Path
from typing import List, Optional, Set

from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.markdown_doc import MarkdownDoc, MarkdownFence
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks
from skillsaw.utils import read_text


class ContentUnclosedFenceRule(Rule):
    """Detect code fences that are opened but never closed.

    An unterminated fence swallows everything after it as code, so every
    content rule is blinded to the rest of the file — a body full of weak
    language or placeholders lints clean.  Scope is fences that run to the
    end of the body at the top level (not nested in a blockquote or list
    item), where appending the matching closing fence is the whole fix.
    """

    autofix_confidence = AutofixConfidence.SUGGEST

    formats = None
    since = "0.17.0"
    repo_types = None

    @property
    def rule_id(self) -> str:
        return "content-unclosed-fence"

    @property
    def description(self) -> str:
        return "Detect code fences opened but never closed, hiding the rest of the file from content rules"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=False)
            if not body or ("```" not in body and "~~~" not in body):
                continue
            fence = self._unclosed_fence(cf.markdown, body)
            if fence is None:
                continue
            opener = fence.markup + fence.info
            violations.append(
                self.violation(
                    f"Unclosed code fence: '{opener}' is never closed — everything "
                    "after it is treated as code and hidden from content rules",
                    block=cf,
                    line=fence.body_line_start,
                )
            )
        return violations

    @staticmethod
    def _unclosed_fence(doc: MarkdownDoc, body: str) -> Optional[MarkdownFence]:
        """Return the unterminated fence running to the end of *body*, if any.

        Only the last fence can reach the end of the body, and an unclosed
        top-level fence always does (nothing can follow it).  Container-nested
        fences are skipped: a column-0 closer would not terminate them (it
        opens a new fence instead), so neither detection nor the fix applies.
        """
        fences = doc.fences()
        if not fences:
            return None
        fence = fences[-1]
        if fence.indented or fence.nested or not fence.markup:
            return None
        # The trailing "" that split("\n") yields for a newline-terminated
        # body is an artifact, not a source line markdown-it counts.
        last_line = doc.body_line_count - (1 if body.endswith("\n") else 0)
        if fence.body_line_end < last_line:
            return None
        if ContentUnclosedFenceRule._is_closing_fence(doc.line(fence.body_line_end), fence.markup):
            return None
        return fence

    @staticmethod
    def _is_closing_fence(line: str, markup: str) -> bool:
        """True when *line* is a valid CommonMark closer for a fence opened
        with *markup*: at most 3 spaces of indent, then a run of the same
        fence character at least as long as the opener, then only whitespace.
        """
        text = line.rstrip()
        run = text.lstrip(" ")
        if len(text) - len(run) > 3:
            return False
        return len(run) >= len(markup) and run == markup[0] * len(run)

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        fixed_paths: Set[Path] = set()
        for v in violations:
            cf = v.block
            if cf is None or v.file_path is None or v.file_path in fixed_paths:
                continue
            body = cf.read_body(strip_code_blocks=False)
            if not body:
                continue
            fence = self._unclosed_fence(cf.markdown, body)
            if fence is None:
                continue
            content = read_text(cf.path)
            if content is None:
                continue
            # Append only when the body ends the file (plain markdown files
            # and frontmattered bodies).  YAML-embedded bodies (.coderabbit
            # instructions, promptfoo prompts) are indented inside a host
            # document — a bare closer at EOF would corrupt it.
            if not content.endswith(body):
                continue
            closer = fence.markup
            fixed = content + ("" if content.endswith("\n") else "\n") + closer + "\n"
            fixed_paths.add(v.file_path)
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=v.file_path,
                    confidence=AutofixConfidence.SUGGEST,
                    original_content=content,
                    fixed_content=fixed,
                    description=(
                        f"Append missing closing fence '{closer}' at end of file "
                        "(move it up if the code block should end earlier)"
                    ),
                    violations_fixed=[v],
                )
            )
        return results
