"""Content missing stop condition rule"""

import re
from typing import Any, Dict, List, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    RegexTimeout,
    _get_body_from_cf,
    gather_all_content_blocks,
    patterns_matching_anywhere,
    regex_timeout,
)

# Wall-clock budget for each user-supplied pattern (issue #316: config
# regexes run against untrusted bodies with a backtracking engine).
_EXTRA_PATTERN_TIMEOUT = 2.0

# Open-ended agentic activity: instructions that start a loop. Loop
# adverbs must sit next to an activity verb — a bare "continuously" or
# "watch for" is usually describing system behavior, not instructing one.
_LOOP_VERBS = r"(?:check|monitor|poll|watch|retry|rerun|run|verify|refresh)"
_LOOP_PATTERNS = [
    (re.compile(p, re.IGNORECASE),)
    for p in (
        r"\bkeep\s+(?:monitoring|checking|polling|watching|retrying|waiting|looping|running)\b",
        r"\bpoll(?:ing)?\s+(?:for|every|the)\b",
        r"\b(?:continuously|repeatedly|indefinitely)\s+" + _LOOP_VERBS + r"\w*\b",
        r"\b" + _LOOP_VERBS + r"\w*\s+(?:continuously|repeatedly|indefinitely)\b",
        r"\bin\s+a\s+loop\b",
        r"\bretry\s+(?:on|if|when)\b",
    )
]

# Anything that bounds the loop: a condition, a count, or a time budget.
_TERMINATOR_PATTERNS = [
    (re.compile(p, re.IGNORECASE),)
    for p in (
        r"\buntil\b",
        r"\b(?:stop|stops|stopping|done|finish|finished|exit|exits|end|ends|give\s+up)\s+"
        r"(?:when|after|once|if|at)\b",
        r"\b(?:may|can|should)\s+stop\b",
        r"\bat\s+most\b",
        r"\bup\s+to\b",
        r"\bno\s+more\s+than\b",
        r"\bmax(?:imum)?\b",
        r"\b\d+\s+(?:times|attempts|retries|iterations|rounds)\b",
        r"\b(?:within|for|after)\s+\d+\s*(?:s|sec|seconds?|m|min|minutes?|h|hours?|days?)\b",
        r"\bonce\b",
        r"\btimeout\b",
        r"\bdeadline\b",
        r"\b(?:exit|completion|success|stopping)\s+criteria\b",
    )
]


class ContentMissingStopConditionRule(Rule):
    """Detect open-ended loop instructions without a stopping condition"""

    formats = None
    since = "0.17.0"
    default_enabled = False

    config_schema = {
        "extra-loop-patterns": {
            "type": "list",
            "default": [],
            "description": (
                "Additional regex patterns that indicate open-ended looping "
                "activity (e.g. project-specific phrasing like 'babysit')"
            ),
        },
        "extra-terminator-patterns": {
            "type": "list",
            "default": [],
            "description": (
                "Additional regex patterns that count as a stopping "
                "condition when found in the same paragraph as a loop "
                "instruction"
            ),
        },
    }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self._extra_loops = self._parse_patterns("extra-loop-patterns")
        self._extra_terminators = self._parse_patterns("extra-terminator-patterns")

    def _parse_patterns(self, key: str) -> List[tuple]:
        raw = self.config.get(key)
        if raw is None:
            raw = []
        if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
            raise ValueError(
                f"'{key}' for rule '{self.rule_id}' must be a list of " f"pattern strings"
            )
        compiled: List[tuple] = []
        for p in raw:
            try:
                compiled.append((re.compile(p, re.IGNORECASE),))
            except re.error as err:
                raise ValueError(
                    f"Invalid pattern {p!r} in '{key}' for rule " f"'{self.rule_id}': {err}"
                ) from err
        return compiled

    @property
    def rule_id(self) -> str:
        return "content-missing-stop-condition"

    @property
    def description(self) -> str:
        return "Detect open-ended loop instructions (keep monitoring, poll, retry) without a stopping condition"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @staticmethod
    def _paragraphs(body: str) -> List[Tuple[int, List[str]]]:
        """Split into (1-based start line, lines) runs of non-blank lines."""
        paragraphs: List[Tuple[int, List[str]]] = []
        current: List[str] = []
        start = 0
        for line_num, line in enumerate(body.splitlines(), 1):
            if line.strip():
                if not current:
                    start = line_num
                current.append(line)
            elif current:
                paragraphs.append((start, current))
                current = []
        if current:
            paragraphs.append((start, current))
        return paragraphs

    def _first_loop_match(self, lines: List[str], active: List[tuple]):
        """(paragraph-relative line offset, phrase) of the first loop match.

        Table rows are skipped: cell text like "Watch for crypto errors"
        is a descriptive matrix entry, not a loop instruction.
        """
        for offset, line in enumerate(lines):
            if line.lstrip().startswith("|"):
                continue
            for (pattern,) in active:
                m = pattern.search(line)
                if m:
                    return offset, m.group()
        return None

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        loop_patterns = _LOOP_PATTERNS + self._extra_loops
        terminator_patterns = _TERMINATOR_PATTERNS + self._extra_terminators
        has_extras = bool(self._extra_loops or self._extra_terminators)
        for cf in gather_all_content_blocks(context):
            body = _get_body_from_cf(cf)
            if not body:
                continue
            try:
                if has_extras:
                    with regex_timeout(_EXTRA_PATTERN_TIMEOUT):
                        violations.extend(
                            self._check_body(cf, body, loop_patterns, terminator_patterns)
                        )
                else:
                    violations.extend(
                        self._check_body(cf, body, loop_patterns, terminator_patterns)
                    )
            except RegexTimeout:
                violations.append(
                    self.violation(
                        f"Skipped file (a configured pattern exceeded the "
                        f"{_EXTRA_PATTERN_TIMEOUT:g}s budget — possible "
                        f"catastrophic backtracking)",
                        block=cf,
                    )
                )
        return violations

    def _check_body(
        self,
        cf,
        body: str,
        loop_patterns: List[tuple],
        terminator_patterns: List[tuple],
    ) -> List[RuleViolation]:
        active_loops = patterns_matching_anywhere(body, loop_patterns)
        if not active_loops:
            return []
        out: List[RuleViolation] = []
        for start, lines in self._paragraphs(body):
            match = self._first_loop_match(lines, active_loops)
            if match is None:
                continue
            paragraph = "\n".join(lines)
            if patterns_matching_anywhere(paragraph, terminator_patterns):
                continue
            offset, phrase = match
            out.append(
                self.violation(
                    f"Open-ended '{phrase}' has no stopping condition in "
                    f"this paragraph — say when to stop (e.g. 'until X', "
                    f"'stop after N minutes', 'at most N retries')",
                    block=cf,
                    line=start + offset,
                )
            )
        return out
