"""Content contradiction rule"""

import re
from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    _required_literal,
    gather_all_content_blocks,
)


class ContentContradictionRule(Rule):
    """Detect likely contradictions within instruction files"""

    autofix_confidence = AutofixConfidence.LLM

    formats = None
    since = "0.7.0"

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files that contain "
            "contradictory instructions. Resolve contradictions by choosing the "
            "more specific or more useful instruction.\n\n"
            "Rules:\n"
            "- When two instructions conflict, keep the more specific one\n"
            "- If both are valid in different contexts, add context qualifiers\n"
            "- Example: 'move fast' + 'write comprehensive tests' → "
            "'Write focused tests for critical paths'\n"
            "- Do NOT remove instructions that aren't contradictory\n"
            "- Preserve markdown formatting"
        )

    _NEGATION_PREFIX_RE = re.compile(r"(?:non[-\s]|not\s+|un|in|im)$", re.IGNORECASE)

    @staticmethod
    def _is_negated(text: str, match: re.Match) -> bool:
        """Check if a regex match is preceded by a negation prefix."""
        start = match.start()
        prefix = text[max(0, start - 4) : start]
        return bool(ContentContradictionRule._NEGATION_PREFIX_RE.search(prefix))

    _CONTRADICTION_PAIRS = [
        (re.compile(pat_a), re.compile(pat_b), desc)
        for pat_a, pat_b, desc in [
            (
                r"\bmove fast\b",
                r"\bcomprehensive tests?\b",
                "'move fast' vs 'comprehensive tests'",
            ),
            (
                r"\bkeep it simple\b",
                r"\bhandle all edge cases\b",
                "'keep it simple' vs 'handle all edge cases'",
            ),
            (
                r"\bdon'?t over-?engineer\b",
                r"\bdetailed architecture\b",
                "'don't over-engineer' vs 'detailed architecture'",
            ),
            (r"\bminimal\b", r"\bexhaustive\b", "'minimal' vs 'exhaustive'"),
            (
                r"\bdon'?t add comments\b",
                r"\bdocument\s+(everything|all|every)\b",
                "'don't add comments' vs 'document everything'",
            ),
            (
                r"\bavoid abstractions?\b",
                r"\bcreate\s+(abstractions?|interfaces?|base\s+class)\b",
                "'avoid abstractions' vs 'create abstractions'",
            ),
        ]
    ]

    @property
    def rule_id(self) -> str:
        return "content-contradiction"

    @property
    def description(self) -> str:
        return "Detect likely contradictions within instruction files using keyword-pair heuristics"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body()
            if not body:
                continue
            body_lower = body.lower()
            for pat_a, pat_b, desc in self._CONTRADICTION_PAIRS:
                lit_a = _required_literal(pat_a.pattern, pat_a.flags)
                if lit_a is not None and lit_a not in body_lower:
                    continue
                has_a = any(not self._is_negated(body_lower, m) for m in pat_a.finditer(body_lower))
                if not has_a:
                    continue
                lit_b = _required_literal(pat_b.pattern, pat_b.flags)
                if lit_b is not None and lit_b not in body_lower:
                    continue
                has_b = any(not self._is_negated(body_lower, m) for m in pat_b.finditer(body_lower))
                if has_a and has_b:
                    violations.append(
                        self.violation(
                            f"Possible contradiction: {desc}",
                            block=cf,
                        )
                    )
        return violations
