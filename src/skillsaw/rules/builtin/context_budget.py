"""
Rule for warning when instruction/config files exceed recommended token limits.
"""

from typing import Any, Dict, List, Optional, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import read_text
from skillsaw.rules.builtin.content_analysis import gather_all_content_files

DEFAULT_LIMITS: Dict[str, Dict[str, int]] = {
    "agents-md": {"warn": 6000, "error": 12000},
    "claude-md": {"warn": 6000, "error": 12000},
    "gemini-md": {"warn": 6000, "error": 12000},
    "skill": {"warn": 3000, "error": 6000},
    "command": {"warn": 2000, "error": 4000},
    "agent": {"warn": 2000, "error": 4000},
    "rule": {"warn": 2000, "error": 4000},
}


def _parse_limit(value: Any) -> Tuple[Optional[int], Optional[int]]:
    """Parse a limit value into (warn, error) thresholds.

    Accepts an int (warn-only) or a dict with 'warn' and/or 'error' keys.
    """
    if isinstance(value, int):
        return value, None
    if isinstance(value, dict):
        warn = value.get("warn")
        error = value.get("error")
        if warn is not None:
            warn = int(warn)
        if error is not None:
            error = int(error)
        return warn, error
    return None, None


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


class ContextBudgetRule(Rule):
    """Warn or error when files exceed recommended token limits"""

    config_schema = {
        "limits": {
            "type": "dict",
            "default": DEFAULT_LIMITS,
            "description": "Token limits per file category (int for warn-only, or {warn, error} dict)",
        },
    }

    @property
    def rule_id(self) -> str:
        return "context-budget"

    @property
    def description(self) -> str:
        return "Warn when instruction or config files exceed recommended token limits"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def _get_limits(self) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        raw = self.config.get("limits", {}) or {}
        merged: Dict[str, Any] = {}
        for key, val in DEFAULT_LIMITS.items():
            merged[key] = val
        for key, val in raw.items():
            merged[key] = val
        return {k: _parse_limit(v) for k, v in merged.items()}

    def _check_file(
        self,
        file_path,
        category: str,
        warn_limit: Optional[int],
        error_limit: Optional[int],
        violations: List[RuleViolation],
    ) -> None:
        content = read_text(file_path)
        if content is None:
            return
        tokens = _estimate_tokens(content)

        if error_limit is not None and tokens > error_limit:
            violations.append(
                self.violation(
                    f"Estimated {tokens:,} tokens exceeds {category} error limit of {error_limit:,}",
                    file_path=file_path,
                    severity=Severity.ERROR,
                )
            )
        elif warn_limit is not None and tokens > warn_limit:
            violations.append(
                self.violation(
                    f"Estimated {tokens:,} tokens exceeds {category} warn limit of {warn_limit:,}",
                    file_path=file_path,
                    severity=Severity.WARNING,
                )
            )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        limits = self._get_limits()

        for cf in gather_all_content_files(context):
            warn_limit, error_limit = limits.get(cf.category, (None, None))
            if warn_limit is not None or error_limit is not None:
                self._check_file(cf.path, cf.category, warn_limit, error_limit, violations)

        return violations
