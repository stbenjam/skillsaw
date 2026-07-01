"""Content banned references rule"""

import re
from typing import List, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    patterns_matching_anywhere,
)


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
    }

    @property
    def rule_id(self) -> str:
        return "content-banned-references"

    @property
    def description(self) -> str:
        return "Detect banned or deprecated model names, APIs, and custom patterns"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def _get_patterns(self) -> List[Tuple[re.Pattern, str]]:
        patterns: List[Tuple[re.Pattern, str]] = []
        if not self.config.get("skip-builtins", False):
            for regex_str, msg in self._BUILTIN_PATTERNS:
                patterns.append((re.compile(regex_str, re.IGNORECASE), msg))
        for entry in self.config.get("banned", []):
            if isinstance(entry, dict) and "pattern" in entry:
                msg = entry.get("message", f"Banned reference: matches '{entry['pattern']}'")
                try:
                    patterns.append((re.compile(entry["pattern"], re.IGNORECASE), msg))
                except re.error:
                    pass
        return patterns

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        patterns = self._get_patterns()
        if not patterns:
            return []
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=False)
            if not body:
                continue
            active = patterns_matching_anywhere(body, patterns)
            if not active:
                continue
            for line_num, line in enumerate(body.splitlines(), 1):
                for pattern, msg in active:
                    if pattern.search(line):
                        violations.append(
                            self.violation(
                                f"Banned reference: {msg}",
                                block=cf,
                                line=line_num,
                            )
                        )
        return violations
