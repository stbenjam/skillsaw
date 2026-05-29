"""Content hook candidate rule"""

import re
from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
)


class ContentHookCandidateRule(Rule):
    """Detect instructions that should be automated hooks"""

    autofix_confidence = AutofixConfidence.LLM

    formats = None
    since = "0.7.0"

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files. Replace "
            "prose instructions that describe automated workflows with a note "
            "to configure the appropriate hook instead.\n\n"
            "Rules:\n"
            "- Replace 'always run X before committing' with a comment suggesting "
            "a pre-commit hook\n"
            "- Replace 'run tests before push' with a suggestion for a pre-push hook\n"
            "- Replace 'after every change, do X' with a PostToolUse hook suggestion\n"
            "- Keep the instruction but rewrite it as a hook configuration reminder\n"
            "- Preserve markdown formatting"
        )

    _HOOK_PATTERNS = [
        (
            re.compile(r"\balways run\s+.+\s+(?:after|before)\b", re.IGNORECASE),
            "PostToolUse or PreToolUse hook",
        ),
        (
            re.compile(r"\bformat\s+(?:code|files?)\s+before\s+committ?ing\b", re.IGNORECASE),
            "pre-commit hook",
        ),
        (
            re.compile(r"\bnever\s+push\s+without\s+(?:running\s+)?tests?\b", re.IGNORECASE),
            "pre-push hook or Stop hook",
        ),
        (re.compile(r"\balways\s+lint\s+before\b", re.IGNORECASE), "pre-commit hook"),
        (
            re.compile(r"\brun\s+tests?\s+before\s+(?:every\s+)?commit\b", re.IGNORECASE),
            "pre-commit hook",
        ),
        (
            re.compile(r"\bafter\s+(?:every|each)\s+(?:change|edit|save)\b", re.IGNORECASE),
            "PostToolUse hook",
        ),
        (re.compile(r"\bbefore\s+(?:every|each)\s+commit\b", re.IGNORECASE), "pre-commit hook"),
    ]

    @property
    def rule_id(self) -> str:
        return "content-hook-candidate"

    @property
    def description(self) -> str:
        return "Detect instructions that should be automated as hooks instead of prose instructions"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body()
            if not body:
                continue
            for line_num, line in enumerate(body.splitlines(), 1):
                for pattern, hook_type in self._HOOK_PATTERNS:
                    if pattern.search(line):
                        violations.append(
                            self.violation(
                                f"Hook candidate: '{line.strip()[:80]}' — consider automating as a {hook_type}",
                                block=cf,
                                line=line_num,
                            )
                        )
                        break
        return violations
