"""Content banned references rule"""

import re
from typing import List, Optional, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    blank_long_tokens,
    RegexTimeout,
    gather_all_content_blocks,
    patterns_matching_anywhere,
    regex_timeout,
)

# Wall-clock budget for a single config-supplied pattern against one file body.
# Untrusted ``.skillsaw.yaml`` patterns run with the backtracking ``re`` engine,
# so an unbounded search can hang lint (issue #316).  Clamped so a hostile or
# careless config can't raise the ceiling to something useless.
_DEFAULT_REGEX_TIMEOUT = 2.0
_MAX_REGEX_TIMEOUT = 10.0

# ── Migration rows ──────────────────────────────────────────────
#
# A line that pairs a retired name with its replacement is retiring the
# name, not recommending it.  The three shapes that say so are a
# column-separated row ("| `claude-2` | `claude-sonnet-5` |"), an arrow
# ("claude-2 -> claude-sonnet-5"), and a key/value mapping ("claude-2":
# "claude-sonnet-5").  All three read the same way inside a fence and in
# prose, so the shape alone decides — no fence or table parse is needed.

# A model identifier: hyphen-joined segments carrying a version, optionally
# namespaced ("anthropic/claude-sonnet-5").  The digit requirement is what
# separates a model name from ordinary hyphenated English ("best-in-class",
# "fast-response") that would otherwise pass for a replacement.
_MODEL_NAME_RE = re.compile(
    r"(?:[A-Za-z][\w.]*/)?(?=[\w./-]*\d)[A-Za-z][\w.]+(?:-[\w.]+)*",
)

# Arrows, requiring whitespace (or a line edge) on both sides so a Python
# return annotation's ``-> str`` still reads as an arrow while a C-style
# ``a->b`` does not split anything.
_ARROW_RE = re.compile(r"(?:^|(?<=\s))(?:-{1,3}>|={1,3}>|→|⇒|➜|⟶)(?=\s|$)")

# The left side of a key/value mapping: a bare identifier, optionally
# quoted and optionally preceded by a list or comment marker.  A colon is
# far too common in prose to split on without this guard.
_MAPPING_KEY_RE = re.compile(r"^[\s\-*#>+]*[\"'`]?[\w./-]+[\"'`]?\s*$")

_PIPE_RE = re.compile(r"\|")


class ContentBannedReferencesRule(Rule):
    """Detect banned or deprecated references in instruction files"""

    formats = None
    since = "0.7.0"

    _BUILTIN_PATTERNS = [
        (r"\bgpt-3\.5\b", "gpt-3.5 is deprecated"),
        (r"\btext-davinci\b", "text-davinci models are retired"),
        (r"\bcode-davinci\b", "code-davinci models are retired"),
        (r"\bclaude-instant\b", "claude-instant is deprecated"),
        (r"\bclaude-2\b", "claude-2 is deprecated"),
        (r"\bclaude-v1\b", "claude-v1 is deprecated"),
        (r"\bclaude-3-opus\b", "claude-3-opus is deprecated"),
        (r"\bclaude-3-sonnet\b", "claude-3-sonnet is deprecated"),
        (r"\bclaude-3-haiku\b", "claude-3-haiku is deprecated"),
        (r"\bclaude-3\.5-sonnet\b", "claude-3.5-sonnet is deprecated"),
        (r"\bclaude-3\.5-haiku\b", "claude-3.5-haiku is deprecated"),
        (r"\b/v1/complete\b", "/v1/complete is deprecated — use /v1/messages"),
    ]

    config_schema = {
        "banned": {
            "type": "list",
            "default": [],
            "description": "Additional banned patterns as list of {pattern, message} dicts",
        },
        "skip-builtins": {
            "type": "bool",
            "default": False,
            "description": "Disable built-in deprecated model/API checks",
        },
        "regex-timeout": {
            "type": "float",
            "default": _DEFAULT_REGEX_TIMEOUT,
            "description": (
                "Per-pattern wall-clock budget (seconds) for custom banned "
                "patterns; guards against catastrophic-backtracking regexes "
                f"(clamped to {_MAX_REGEX_TIMEOUT:g}s max)"
            ),
        },
        "report-migrations": {
            "type": "bool",
            "default": False,
            "description": (
                "Report a banned name even on a line that maps it to a "
                "current replacement (a table row, arrow, or key/value entry)"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "content-banned-references"

    @property
    def description(self) -> str:
        return "Detect banned or deprecated model names, APIs, and custom patterns"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def _builtin_patterns(self) -> List[Tuple[re.Pattern, str]]:
        """Trusted, curated patterns — safe to run without a time budget."""
        if self.config.get("skip-builtins", False):
            return []
        return [
            (re.compile(regex_str, re.IGNORECASE), msg) for regex_str, msg in self._BUILTIN_PATTERNS
        ]

    def _config_patterns(self) -> List[Tuple[re.Pattern, str]]:
        """Untrusted patterns from ``.skillsaw.yaml`` — run under a time budget."""
        patterns: List[Tuple[re.Pattern, str]] = []
        for entry in self.config.get("banned", []):
            if isinstance(entry, dict) and "pattern" in entry:
                msg = entry.get("message", f"Banned reference: matches '{entry['pattern']}'")
                try:
                    patterns.append((re.compile(entry["pattern"], re.IGNORECASE), msg))
                except re.error:
                    pass
        return patterns

    def _regex_timeout(self) -> float:
        try:
            value = float(self.config.get("regex-timeout", _DEFAULT_REGEX_TIMEOUT))
        except (TypeError, ValueError):
            value = _DEFAULT_REGEX_TIMEOUT
        if value <= 0:
            return 0.0
        return min(value, _MAX_REGEX_TIMEOUT)

    def _operands(self, line: str) -> List[Tuple[int, int]]:
        """Spans of *line* split on whichever mapping separator it uses.

        Empty when the line maps nothing.  Precedence runs from the most
        explicit separator to the least: a column-separated row, then an
        arrow, then a single key/value colon.
        """
        stripped = line.strip()
        # A pipe row may omit its outer delimiters, but then every cell must
        # be one token: `grep claude-2 | grep o3` is a shell pipeline, not a
        # migration.
        if "|" in stripped:
            cells = self._split_at(line, [m.span() for m in _PIPE_RE.finditer(line)])
            filled = [cell for cell in (line[start:end].strip() for start, end in cells) if cell]
            delimited = stripped.startswith("|") or stripped.endswith("|")
            if len(filled) >= 2 and (delimited or all(len(cell.split()) == 1 for cell in filled)):
                return cells
        arrows = [m.span() for m in _ARROW_RE.finditer(line)]
        if arrows:
            return self._split_at(line, arrows)
        colon = line.find(":")
        if colon > 0 and _MAPPING_KEY_RE.match(line[:colon]):
            return self._split_at(line, [(colon, colon + 1)])
        return []

    @staticmethod
    def _split_at(line: str, separators: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        spans: List[Tuple[int, int]] = []
        cursor = 0
        for start, end in separators:
            spans.append((cursor, start))
            cursor = end
        spans.append((cursor, len(line)))
        return spans

    def _migration_cutoff(self, line: str, deprecated: List[Tuple[re.Pattern, str]]) -> int:
        """Index before which a banned name on *line* is being retired.

        Returns the offset of the operand naming the replacement, or -1
        when the line maps no banned name to a current model.
        """
        operands = self._operands(line)
        if len(operands) < 2:
            return -1
        for start, end in reversed(operands[1:]):
            operand = line[start:end]
            # Linear: a replacement carries a digit and is never longer than
            # a token. Without these two checks the lookahead in
            # _MODEL_NAME_RE rescans a long digit-free operand from every
            # position, and one such line stalls the lint.
            if not any(ch.isdigit() for ch in operand):
                continue
            for match in _MODEL_NAME_RE.finditer(blank_long_tokens(operand)):
                name = match.group()
                if not any(pattern.search(name) for pattern, _ in deprecated):
                    return start
        return -1

    def _scan(
        self,
        cf,
        body: str,
        patterns: List[Tuple[re.Pattern, str]],
        deprecated: Optional[List[Tuple[re.Pattern, str]]],
    ) -> List[RuleViolation]:
        active = patterns_matching_anywhere(body, patterns)
        if not active:
            return []
        out: List[RuleViolation] = []
        for line_num, line in enumerate(body.splitlines(), 1):
            cutoff = None
            for pattern, msg in active:
                if not pattern.search(line):
                    continue
                if deprecated is not None:
                    # Only lines that actually name something banned are
                    # worth the mapping analysis.
                    if cutoff is None:
                        cutoff = self._migration_cutoff(line, deprecated)
                    if cutoff >= 0 and all(m.end() <= cutoff for m in pattern.finditer(line)):
                        continue
                out.append(self.violation(f"Banned reference: {msg}", block=cf, line=line_num))
        return out

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        builtin = self._builtin_patterns()
        config = self._config_patterns()
        if not builtin and not config:
            return []
        timeout = self._regex_timeout()
        # A replacement has to be a model skillsaw does not already know to be
        # retired, so a table that migrates onto a deprecated name still
        # reports the name it migrates onto.  Only the curated built-ins vet
        # the replacement: config patterns are project vocabulary rather than
        # deprecation knowledge, and running them here would escape the
        # per-pattern time budget.
        deprecated = None if self.setting("report-migrations") else builtin
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=False)
            if not body:
                continue
            # Trusted built-ins run without a budget.
            violations.extend(self._scan(cf, body, builtin, deprecated))
            # Each untrusted config pattern is bounded independently so one
            # catastrophic-backtracking regex can't hang lint (issue #316) and
            # so the offending pattern can be named in the diagnostic.
            # A configured pattern is project policy, not deprecation
            # knowledge: `forbidden-model: gpt-5-mini` is still a use of the
            # forbidden name, so migration suppression never applies to it.
            for pat, msg in config:
                try:
                    with regex_timeout(timeout):
                        violations.extend(self._scan(cf, body, [(pat, msg)], None))
                except RegexTimeout:
                    violations.append(
                        self.violation(
                            "Skipped banned pattern (exceeded "
                            f"{timeout:g}s budget — possible catastrophic backtracking): "
                            f"{pat.pattern!r}",
                            block=cf,
                        )
                    )
        return violations
