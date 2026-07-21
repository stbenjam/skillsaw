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
# two rules agree on what counts as a directive.  This rule additionally
# strips leading emphasis markers before the gate (see _LEAD_EMPHASIS_RE)
# so bold-lead bullets are recognized.
_IMPERATIVE_RE = InstructionBudgetAnalyzer._IMPERATIVE_RE

_WORD_RE = re.compile(r"[a-z0-9']+")

# "Run 2: Failed tests = [...]" — an enumeration label, not an imperative.
# The leading word only looks like a verb; lists of these are example data.
_ENUMERATION_RE = re.compile(r"^\s*(?:[-*]\s*)?\w+\s+\d+\s*:")

# Emphasis markers leading a directive ('- **Always run make test.**',
# '**Never do X**') hide the verb from the imperative gate.  Strip them
# for gating only — _normalize() is already emphasis-insensitive, so a
# bolded directive and its plain twin compare equal.  The (?=\S) guard
# keeps a bare '*' bullet marker ('- * item') from being treated as
# emphasis.  [*_]+ matches the same strings as an alternation of
# **/__/*/_ runs but linearly — the alternation form backtracks
# exponentially on long marker runs (CodeQL js/redos-style finding).
_LEAD_EMPHASIS_RE = re.compile(r"^(\s*[-*]?\s*)[*_]+(?=\S)")

# A fence marker line inside an HTML block (CommonMark parses the whole
# <Bad>```…```</Bad> region as one html_block token, so markdown-it
# reports no fence there).
_HTML_FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")

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
                # The trailing lookahead rejects incidental phrasing such
                # as troubleshooting notes ("If you get permission errors,
                # check your kubeconfig") — those describe a failure mode,
                # not an approval policy.  The lookahead follows fixed
                # literal alternations, so no backtrackable quantifier can
                # truncate into a false accept.
                r"\b(?:get|obtain|require)s?\s+(?:explicit\s+)?"
                r"(?:approval|confirmation|permission)\b"
                r"(?!\s+(?:errors?|denied|issues?|problems?)\b)",
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
    _DEFAULT_MIN_DISTANCE = 4
    # High enough that realistic large instruction files (measured: a
    # 2000-line CLAUDE.md with ~1150 directives) are still fully scanned,
    # while bounding the O(n^2) similarity stage on degenerate or
    # adversarial inputs whose word-multiset overlap defeats the
    # quick_ratio prefilter.
    _DEFAULT_MAX_DIRECTIVES = 1500

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
        "min-line-distance": {
            "type": "int",
            "default": _DEFAULT_MIN_DISTANCE,
            "description": (
                "Minimum number of lines between two directives before they "
                "are compared — neighboring similar bullets are usually "
                "intentional parallel structure, not repetition"
            ),
        },
        "similarity-max-directives": {
            "type": "int",
            "default": _DEFAULT_MAX_DIRECTIVES,
            "description": (
                "Maximum number of directives per file entering pairwise "
                "similarity comparison; directives beyond the cap are still "
                "checked for exact repeats (a linear scan) but skip the "
                "quadratic near-duplicate stage"
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

        min_distance = self.config.get("min-line-distance", self._DEFAULT_MIN_DISTANCE)
        if not isinstance(min_distance, int) or isinstance(min_distance, bool):
            raise ValueError(
                f"'min-line-distance' for rule '{self.rule_id}' must be an "
                f"integer, got {type(min_distance).__name__}"
            )
        if min_distance < 1:
            raise ValueError(
                f"'min-line-distance' for rule '{self.rule_id}' must be at "
                f"least 1, got {min_distance}"
            )
        self._min_distance = min_distance

        max_directives = self.config.get("similarity-max-directives", self._DEFAULT_MAX_DIRECTIVES)
        if not isinstance(max_directives, int) or isinstance(max_directives, bool):
            raise ValueError(
                f"'similarity-max-directives' for rule '{self.rule_id}' must "
                f"be an integer, got {type(max_directives).__name__}"
            )
        if max_directives < 2:
            raise ValueError(
                f"'similarity-max-directives' for rule '{self.rule_id}' must "
                f"be at least 2, got {max_directives}"
            )
        self._max_directives = max_directives
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
        """(prose, fence start lines) — fenced code blanked, inline code kept.

        ``read_body(strip_code_blocks=True)`` also blanks inline code
        spans, but a code span is often the only token distinguishing two
        directives ('Run `make test` …' vs 'Run `make lint` …') —
        comparing without it manufactures false duplicates.
        """
        body = cf.read_body(strip_code_blocks=False)
        if not body:
            return None, frozenset()
        lines = body.splitlines()
        fence_starts = set()
        for fence in cf.markdown.fences():
            fence_starts.add(fence.body_line_start)
            for i in range(fence.body_line_start - 1, min(fence.body_line_end, len(lines))):
                lines[i] = ""
        for start0, end0 in ContentRepeatedDirectiveRule._html_block_line_spans(cf.markdown):
            ContentRepeatedDirectiveRule._blank_html_block_fences(lines, fence_starts, start0, end0)
        return "\n".join(lines), frozenset(fence_starts)

    @staticmethod
    def _html_block_line_spans(doc) -> List[Tuple[int, int]]:
        """0-based (start, end) line spans of block-level HTML tokens.

        Read from the markdown-it token stream (MarkdownDoc exposes no
        public html-block accessor): a fenced example wrapped in an HTML
        tag with no intervening blank line — the common <Bad>/<Good>
        pattern in skill-authoring docs — is swallowed into one
        ``html_block`` token, so ``fences()`` never reports the fence.
        """
        return [
            (t.map[0], t.map[1])
            for t in getattr(doc, "_tokens", [])
            if t.type == "html_block" and t.map
        ]

    @staticmethod
    def _blank_html_block_fences(
        lines: List[str], fence_starts: set, start0: int, end0: int
    ) -> None:
        """Blank fence marker and interior lines inside an HTML block.

        The quoted example text inside such a fence is illustrative, not a
        live directive.  Non-fence lines of the HTML block (tags, prose)
        keep their current treatment.
        """
        in_fence = False
        fence_char = ""
        fence_len = 0
        for i in range(start0, min(end0, len(lines))):
            stripped = lines[i].strip()
            if not in_fence:
                m = _HTML_FENCE_OPEN_RE.match(stripped)
                if m:
                    marker = m.group(1)
                    fence_char = marker[0]
                    fence_len = len(marker)
                    in_fence = True
                    fence_starts.add(i + 1)
                    lines[i] = ""
            else:
                closes = (
                    bool(stripped) and set(stripped) == {fence_char} and len(stripped) >= fence_len
                )
                lines[i] = ""
                if closes:
                    in_fence = False

    @staticmethod
    def _normalize(line: str) -> List[str]:
        return _WORD_RE.findall(line.lower())

    def _extract_directives(self, body: str, fence_starts: frozenset) -> List[_Directive]:
        directives: List[_Directive] = []
        for line_num, line in enumerate(body.splitlines(), 1):
            # Gate on a copy with leading emphasis markers stripped so
            # '- **Always run make test.**' is recognized; the original
            # line is kept for the message text and normalization.
            gate = _LEAD_EMPHASIS_RE.sub(r"\1", line)
            if not _IMPERATIVE_RE.match(gate):
                continue
            if _ENUMERATION_RE.match(gate):
                continue
            # "Add to `customizations.vscode.extensions`:" followed by a
            # fence is a caption for the code below — parallel sections
            # repeat the caption while the code (the real content) differs.
            if line.rstrip().endswith(":") and (
                line_num + 1 in fence_starts or line_num + 2 in fence_starts
            ):
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
        self, cf: ContentBlock, body: str, fence_starts: frozenset, reported: set
    ) -> List[RuleViolation]:
        directives = self._extract_directives(body, fence_starts)
        if len(directives) < 2:
            return []
        threshold = self._threshold
        violations: List[RuleViolation] = []
        # Bound the O(n^2) stage: only the first `similarity-max-directives`
        # directives enter pairwise comparison.  Directives beyond the cap
        # are still checked for exact repeats below — a linear scan — so
        # the highest-signal finding survives on degenerate inputs.
        compared = directives[: self._max_directives]
        matcher = SequenceMatcher(autojunk=False)
        for j in range(1, len(compared)):
            anchor = compared[j]
            matcher.set_seq2(anchor.words)
            anchor_len = len(anchor.words)
            for i in range(j):
                other = compared[i]
                if anchor.body_line - other.body_line < self._min_distance:
                    continue
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
        if len(directives) > len(compared):
            violations.extend(
                self._exact_repeat_violations(cf, directives, len(compared), reported)
            )
        return violations

    def _exact_repeat_violations(
        self, cf: ContentBlock, directives: List[_Directive], cap: int, reported: set
    ) -> List[RuleViolation]:
        """Exact-repeat detection for directives past the similarity cap.

        A linear scan keyed on normalized words: each beyond-cap directive
        is compared against the earliest earlier identical directive, the
        same pair the pairwise loop would have reported first.
        """
        violations: List[RuleViolation] = []
        first_seen: Dict[tuple, _Directive] = {}
        for idx, directive in enumerate(directives):
            key = tuple(directive.words)
            if idx >= cap:
                earlier = first_seen.get(key)
                if (
                    earlier is not None
                    and directive.body_line - earlier.body_line >= self._min_distance
                    and earlier.body_line not in reported
                    and directive.body_line not in reported
                ):
                    violations.append(
                        self.violation(
                            f"Directive '{self._truncate(directive.text)}' repeats "
                            f"the directive at line {cf.file_line(earlier.body_line)} — "
                            f"state each instruction once",
                            block=cf,
                            line=directive.body_line,
                            severity=(
                                Severity.INFO
                                if isinstance(cf, self._REFERENCE_BLOCK_TYPES)
                                else None
                            ),
                        )
                    )
                    reported.add(directive.body_line)
            first_seen.setdefault(key, directive)
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
                # INFO, not the rule severity: cluster matches in long
                # workflow files are often step-scoped ("this step requires
                # confirmation" for two different steps) rather than one
                # blanket policy stated twice — worth a look, not a defect.
                violations.append(
                    self.violation(
                        f"'{phrase}' restates the {name} policy already "
                        f"stated at line {cf.file_line(first_line)} "
                        f"('{first_phrase}') — state the policy once",
                        block=cf,
                        line=line_num,
                        severity=Severity.INFO,
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
            # A heading naming a policy section ("### Require Explicit
            # Approval") is not a statement of the policy, and an HTML
            # comment (suppression directives, commented-out prose) is
            # not delivered to the agent at all.
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith("<!--"):
                continue
            for (pattern,) in active:
                m = pattern.search(line)
                if m:
                    matches.append((line_num, m.group()))
                    break
        return matches

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            body, fence_starts = self._scan_body(cf)
            if not body:
                continue
            reported: set = set()
            violations.extend(self._similarity_violations(cf, body, fence_starts, reported))
            violations.extend(self._cluster_violations(cf, body, reported))
        return violations
