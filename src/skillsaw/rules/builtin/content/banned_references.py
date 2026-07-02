"""Content banned references rule"""

import re
from typing import List, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
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

    def _scan(self, cf, body: str, patterns: List[Tuple[re.Pattern, str]]) -> List[RuleViolation]:
        active = patterns_matching_anywhere(body, patterns)
        if not active:
            return []
        out: List[RuleViolation] = []
        for line_num, line in enumerate(body.splitlines(), 1):
            for pattern, msg in active:
                if pattern.search(line):
                    out.append(self.violation(f"Banned reference: {msg}", block=cf, line=line_num))
        return out

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        builtin = self._builtin_patterns()
        config = self._config_patterns()
        if not builtin and not config:
            return []
        timeout = self._regex_timeout()
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=False)
            if not body:
                continue
            # Trusted built-ins run without a budget.
            violations.extend(self._scan(cf, body, builtin))
            # Each untrusted config pattern is bounded independently so one
            # catastrophic-backtracking regex can't hang lint (issue #316) and
            # so the offending pattern can be named in the diagnostic.
            for pat, msg in config:
                try:
                    with regex_timeout(timeout):
                        violations.extend(self._scan(cf, body, [(pat, msg)]))
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
