"""Content negative only rule"""

import re
from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
)


class ContentNegativeOnlyRule(Rule):
    """Detect 'never/don't/avoid X' without a positive alternative"""

    autofix_confidence = AutofixConfidence.LLM

    formats = None
    since = "0.7.0"

    _NEGATIVE_RE = re.compile(
        r"(?:never\s+use|don'?t\s+use|avoid\s+using|do\s+not\s+use|never\s+do|don'?t\s+do)\s+",
        re.IGNORECASE,
    )
    _POSITIVE_RE = re.compile(
        r"(?:"
        r"\binstead\b"
        r"|instead\s*,?\s+use"
        r"|prefer\s+\S+"
        r"|replace\s+with"
        r"|\buse\s+\S+"
        r"|\bapply\s+\S+"
        r"|\bset\s+\S+"
        r"|\bchoose\s+\S+"
        r"|\bswitch\s+to\b"
        r"|\bopt\s+for\b"
        r"|\brather\s+than\b"
        r"|\balways\b"
        r"|\bfollow\s+\S+"
        r"|\badd\s+\S+"
        r"|\bgenerate\s+\S+"
        r"|\bsummarize\s+\S+"
        r")",
        re.IGNORECASE,
    )
    _SCOPE_BOUNDARY_RE = re.compile(
        r"(?:don[''']?t|do\s+not)\s+use\b.*\bwhen\s*[:*]",
        re.IGNORECASE,
    )

    @property
    def rule_id(self) -> str:
        return "content-negative-only"

    @property
    def description(self) -> str:
        return "Detect prohibitions without a positive alternative (agent has no path forward)"

    def default_severity(self) -> Severity:
        return Severity.INFO

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files. Rewrite "
            'negative-only instructions ("don\'t do X", "never use X", '
            '"avoid X") to include a positive alternative.\n\n'
            "Rules:\n"
            "- Keep the prohibition but add what to do instead\n"
            "- Example: 'Don't use var' → 'Use const or let instead of var'\n"
            "- Example: 'Never commit secrets' → 'Store secrets in environment "
            "variables, never commit them to the repository'\n"
            "- Infer the positive alternative from context\n"
            "- Do NOT change the meaning of the prohibition\n"
            "- Preserve markdown formatting"
        )

    def _has_positive_alternative(self, line, lines, line_idx):
        neg_match = self._NEGATIVE_RE.search(line)
        if not neg_match:
            return False

        text_before_neg = line[: neg_match.start()]
        if self._POSITIVE_RE.search(text_before_neg):
            return True

        text_after_neg = line[neg_match.end() :]
        if self._POSITIVE_RE.search(text_after_neg):
            return True

        start = max(0, line_idx - 2)
        end = min(len(lines), line_idx + 5)
        for j in range(start, end):
            if j == line_idx:
                continue
            if self._POSITIVE_RE.search(lines[j]):
                return True

        return False

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body()
            if not body:
                continue
            lines = body.splitlines()
            for i, line in enumerate(lines):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if not self._NEGATIVE_RE.search(line):
                    continue
                if self._SCOPE_BOUNDARY_RE.search(line):
                    continue
                if not self._has_positive_alternative(line, lines, i):
                    violations.append(
                        self.violation(
                            f"Negative-only instruction without alternative: '{line.strip()[:80]}'",
                            block=cf,
                            line=i + 1,
                        )
                    )
        return violations
