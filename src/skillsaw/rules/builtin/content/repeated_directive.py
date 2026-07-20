"""Content repeated directive rule"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.blocks import ContentBlock
from skillsaw.rules.builtin.content_analysis import (
    InstructionBudgetAnalyzer,
    RegexTimeout,
    SkillRefBlock,
    gather_all_content_blocks,
    patterns_matching_anywhere,
    regex_timeout,
)

# Reuse the imperative-line definition from the instruction budget so the
# two rules agree on what counts as a directive.
_IMPERATIVE_RE = InstructionBudgetAnalyzer._IMPERATIVE_RE

_WORD_RE = re.compile(r"[a-z0-9']+")

# Wall-clock budget for each user-supplied cluster pattern (issue #316:
# config regexes run against untrusted bodies with a backtracking engine).
_EXTRA_PATTERN_TIMEOUT = 2.0

# Phrase clusters where different wordings state the same policy. Two
# different lines matching the same cluster restate one rule and should
# be consolidated into a single statement.
_DEFAULT_CLUSTERS: List[Tuple[str, List[re.Pattern]]] = [
    (
        "approval",
        [
            re.compile(p, re.IGNORECASE)
            for p in (
                r"\bask\s+(?:the\s+user\s+)?(?:first|before)\b",
                r"\bask\s+for\s+(?:approval|confirmation|permission)\b",
                r"\bwait\s+for\s+(?:user\s+)?(?:approval|confirmation|permission)\b",
                r"\b(?:get|obtain|require)s?\s+(?:explicit\s+)?(?:approval|confirmation|permission)\b",
                r"\bconfirm\s+(?:with\s+the\s+user\s+)?before\b",
                r"\bcheck\s+with\s+the\s+user\s+before\b",
                r"\bdo\s+not\s+proceed\s+without\s+(?:approval|confirmation|asking)\b",
            )
        ],
    ),
]


@dataclass
class _Directive:
    """An imperative line prepared for pairwise comparison."""

    body_line: int
    text: str
    words: List[str] = field(repr=False)


class ContentRepeatedDirectiveRule(Rule):
    """Detect the same directive stated more than once within a file"""

    formats = None
    since = "0.17.0"

    _DEFAULT_THRESHOLD = 0.85
    _DEFAULT_MIN_WORDS = 4

    config_schema = {
        "similarity-threshold": {
            "type": "float",
            "default": _DEFAULT_THRESHOLD,
            "description": (
                "Similarity ratio (0-1] at or above which two directive lines "
                "in the same file are considered restatements; identical "
                "lines always fire"
            ),
        },
        "min-directive-words": {
            "type": "int",
            "default": _DEFAULT_MIN_WORDS,
            "description": (
                "Minimum number of words a directive line must contain to "
                "participate in similarity comparison (phrase clusters are "
                "not length-limited)"
            ),
        },
        "extra-clusters": {
            "type": "dict",
            "default": {},
            "description": (
                "Additional phrase clusters keyed by cluster name, each a "
                "list of regex patterns that express the same policy; two "
                "different lines matching one cluster are flagged as "
                "restatements"
            ),
        },
    }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        threshold = self.config.get("similarity-threshold", self._DEFAULT_THRESHOLD)
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise ValueError(
                f"'similarity-threshold' for rule '{self.rule_id}' must be a "
                f"number, got {type(threshold).__name__}"
            )
        if not 0 < threshold <= 1:
            raise ValueError(
                f"'similarity-threshold' for rule '{self.rule_id}' must be "
                f"greater than 0 and at most 1, got {threshold}"
            )
        self._threshold = float(threshold)

        min_words = self.config.get("min-directive-words", self._DEFAULT_MIN_WORDS)
        if not isinstance(min_words, int) or isinstance(min_words, bool):
            raise ValueError(
                f"'min-directive-words' for rule '{self.rule_id}' must be an "
                f"integer, got {type(min_words).__name__}"
            )
        if min_words < 2:
            raise ValueError(
                f"'min-directive-words' for rule '{self.rule_id}' must be at "
                f"least 2, got {min_words}"
            )
        self._min_words = min_words
        self._extra_clusters = self._parse_extra_clusters()

    def _parse_extra_clusters(self) -> List[Tuple[str, List[re.Pattern]]]:
        raw = self.config.get("extra-clusters")
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(
                f"'extra-clusters' for rule '{self.rule_id}' must be a mapping "
                f"of cluster name to a list of patterns, got {type(raw).__name__}"
            )
        clusters: List[Tuple[str, List[re.Pattern]]] = []
        for name, patterns in raw.items():
            if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
                raise ValueError(
                    f"Cluster '{name}' for rule '{self.rule_id}' must be a "
                    f"list of pattern strings"
                )
            compiled: List[re.Pattern] = []
            for p in patterns:
                try:
                    compiled.append(re.compile(p, re.IGNORECASE))
                except re.error as err:
                    raise ValueError(
                        f"Invalid pattern {p!r} in cluster '{name}' for rule "
                        f"'{self.rule_id}': {err}"
                    ) from err
            if compiled:
                clusters.append((name, compiled))
        return clusters

    @property
    def rule_id(self) -> str:
        return "content-repeated-directive"

    @property
    def description(self) -> str:
        return "Detect the same directive stated more than once within a file"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    _REFERENCE_BLOCK_TYPES = (SkillRefBlock,)

    @staticmethod
    def _scan_body(cf: ContentBlock):
        """Raw prose with fenced-code lines blanked, inline code preserved.

        ``read_body(strip_code_blocks=True)`` also blanks inline code
        spans, but a code span is often the only token distinguishing two
        directives ('Run `make test` …' vs 'Run `make lint` …') —
        comparing without it manufactures false duplicates.
        """
        body = cf.read_body(strip_code_blocks=False)
        if not body:
            return None
        lines = body.splitlines()
        for fence in cf.markdown.fences():
            for i in range(fence.body_line_start - 1, min(fence.body_line_end, len(lines))):
                lines[i] = ""
        return "\n".join(lines)

    @staticmethod
    def _normalize(line: str) -> List[str]:
        return _WORD_RE.findall(line.lower())

    def _extract_directives(self, body: str) -> List[_Directive]:
        directives: List[_Directive] = []
        for line_num, line in enumerate(body.splitlines(), 1):
            if not _IMPERATIVE_RE.match(line):
                continue
            words = self._normalize(line)
            if len(words) < self._min_words:
                continue
            directives.append(_Directive(line_num, line.strip(), words))
        return directives

    @staticmethod
    def _truncate(text: str, limit: int = 60) -> str:
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _similarity_violations(
        self, cf: ContentBlock, body: str, reported: set
    ) -> List[RuleViolation]:
        directives = self._extract_directives(body)
        if len(directives) < 2:
            return []
        threshold = self._threshold
        violations: List[RuleViolation] = []
        matcher = SequenceMatcher(autojunk=False)
        for j in range(1, len(directives)):
            anchor = directives[j]
            matcher.set_seq2(anchor.words)
            anchor_len = len(anchor.words)
            for i in range(j):
                other = directives[i]
                if other.body_line in reported:
                    continue
                other_len = len(other.words)
                # real_quick_ratio() length bound computed from stored
                # lengths — results-identical to calling ratio() directly.
                if 2.0 * min(other_len, anchor_len) / (other_len + anchor_len) < threshold:
                    continue
                matcher.set_seq1(other.words)
                if matcher.quick_ratio() < threshold:
                    continue
                ratio = matcher.ratio()
                if ratio < threshold:
                    continue
                percent = int(ratio * 100)
                qualifier = "repeats" if ratio == 1.0 else f"restates ({percent}% similar)"
                violations.append(
                    self.violation(
                        f"Directive '{self._truncate(anchor.text)}' {qualifier} "
                        f"the directive at line {cf.file_line(other.body_line)} — "
                        f"state each instruction once",
                        block=cf,
                        line=anchor.body_line,
                        severity=(
                            Severity.INFO if isinstance(cf, self._REFERENCE_BLOCK_TYPES) else None
                        ),
                    )
                )
                reported.add(anchor.body_line)
                break
        return violations

    def _cluster_violations(
        self, cf: ContentBlock, body: str, reported: set
    ) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        untrusted_names = {name for name, _ in self._extra_clusters}
        for name, patterns in list(_DEFAULT_CLUSTERS) + self._extra_clusters:
            tuples = [(p,) for p in patterns]
            try:
                if name in untrusted_names:
                    with regex_timeout(_EXTRA_PATTERN_TIMEOUT):
                        matches = self._cluster_matches(body, tuples)
                else:
                    matches = self._cluster_matches(body, tuples)
            except RegexTimeout:
                violations.append(
                    self.violation(
                        f"Skipped cluster '{name}' (exceeded "
                        f"{_EXTRA_PATTERN_TIMEOUT:g}s budget — possible "
                        f"catastrophic backtracking)",
                        block=cf,
                    )
                )
                continue
            if len(matches) < 2:
                continue
            first_line, first_phrase = matches[0]
            for line_num, phrase in matches[1:]:
                if line_num in reported:
                    continue
                violations.append(
                    self.violation(
                        f"'{phrase}' restates the {name} policy already "
                        f"stated at line {cf.file_line(first_line)} "
                        f"('{first_phrase}') — state the policy once",
                        block=cf,
                        line=line_num,
                        severity=(
                            Severity.INFO if isinstance(cf, self._REFERENCE_BLOCK_TYPES) else None
                        ),
                    )
                )
                reported.add(line_num)
        return violations

    @staticmethod
    def _cluster_matches(body: str, tuples: List[tuple]) -> List[Tuple[int, str]]:
        """(body line, matched phrase) for lines matching any cluster pattern.

        One match per line — a line restating a policy twice is still one
        statement of it.
        """
        active = patterns_matching_anywhere(body, tuples)
        if not active:
            return []
        matches: List[Tuple[int, str]] = []
        for line_num, line in enumerate(body.splitlines(), 1):
            for (pattern,) in active:
                m = pattern.search(line)
                if m:
                    matches.append((line_num, m.group()))
                    break
        return matches

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            body = self._scan_body(cf)
            if not body:
                continue
            reported: set = set()
            violations.extend(self._similarity_violations(cf, body, reported))
            violations.extend(self._cluster_violations(cf, body, reported))
        return violations
