"""Content emphasis density rule"""

from typing import Any, Dict, List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    _CRITICAL_KEYWORDS,
    _get_body_from_cf,
    gather_all_content_blocks,
)


class ContentEmphasisDensityRule(Rule):
    """Detect emphasis inflation — when everything is critical, nothing is"""

    formats = None
    since = "0.17.0"

    _DEFAULT_MAX_RATIO = 0.2
    _DEFAULT_MIN_EMPHASIZED = 5

    config_schema = {
        "max-ratio": {
            "type": "float",
            "default": _DEFAULT_MAX_RATIO,
            "description": (
                "Maximum fraction (0-1, exclusive) of non-blank body lines "
                "that may carry critical emphasis (IMPORTANT, MUST, NEVER, "
                "ALWAYS, CRITICAL, WARNING, REQUIRED) before the file is "
                "flagged"
            ),
        },
        "min-emphasized": {
            "type": "int",
            "default": _DEFAULT_MIN_EMPHASIZED,
            "description": (
                "Minimum number of emphasized lines before the rule fires — "
                "keeps short files with a couple of MUSTs from being flagged"
            ),
        },
    }

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        max_ratio = self.config.get("max-ratio", self._DEFAULT_MAX_RATIO)
        if not isinstance(max_ratio, (int, float)) or isinstance(max_ratio, bool):
            raise ValueError(
                f"'max-ratio' for rule '{self.rule_id}' must be a number, "
                f"got {type(max_ratio).__name__}"
            )
        if not 0 < max_ratio < 1:
            raise ValueError(
                f"'max-ratio' for rule '{self.rule_id}' must be greater than "
                f"0 and less than 1, got {max_ratio}"
            )
        self._max_ratio = float(max_ratio)

        min_emphasized = self.config.get("min-emphasized", self._DEFAULT_MIN_EMPHASIZED)
        if not isinstance(min_emphasized, int) or isinstance(min_emphasized, bool):
            raise ValueError(
                f"'min-emphasized' for rule '{self.rule_id}' must be an "
                f"integer, got {type(min_emphasized).__name__}"
            )
        if min_emphasized < 1:
            raise ValueError(
                f"'min-emphasized' for rule '{self.rule_id}' must be at "
                f"least 1, got {min_emphasized}"
            )
        self._min_emphasized = min_emphasized

    @property
    def rule_id(self) -> str:
        return "content-emphasis-density"

    @property
    def description(self) -> str:
        return "Detect emphasis inflation: too many ALWAYS/NEVER/MUST/IMPORTANT directives per file"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for cf in gather_all_content_blocks(context):
            body = _get_body_from_cf(cf)
            if not body:
                continue
            total = 0
            emphasized = 0
            for line in body.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                # Table rows are structured spec data — "| `exp` | MUST be
                # present |" is RFC-2119 language in a claims matrix, not
                # steering emphasis.
                if stripped.startswith("|"):
                    continue
                total += 1
                if _CRITICAL_KEYWORDS.search(line):
                    emphasized += 1
            if emphasized < self._min_emphasized:
                continue
            ratio = emphasized / total
            if ratio <= self._max_ratio:
                continue
            violations.append(
                self.violation(
                    f"{emphasized} of {total} lines carry critical emphasis "
                    f"(IMPORTANT/MUST/NEVER/ALWAYS/...) — {int(ratio * 100)}% "
                    f"exceeds the {int(self._max_ratio * 100)}% limit; when "
                    f"everything is emphasized nothing stands out. Reserve "
                    f"emphasis for the few rules that matter most",
                    block=cf,
                )
            )
        return violations
