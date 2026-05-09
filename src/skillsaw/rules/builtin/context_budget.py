"""
Rule for warning when instruction/config files exceed recommended token limits.
"""

from typing import Any, Dict, List, Optional, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, ALL_INSTRUCTION_FORMATS
from skillsaw.rules.builtin.utils import read_text

DEFAULT_LIMITS: Dict[str, Dict[str, int]] = {
    "agents-md": {"warn": 6000, "error": 12000},
    "claude-md": {"warn": 6000, "error": 12000},
    "gemini-md": {"warn": 6000, "error": 12000},
    "skill": {"warn": 3000, "error": 6000},
    "command": {"warn": 2000, "error": 4000},
    "agent": {"warn": 2000, "error": 4000},
    "rule": {"warn": 2000, "error": 4000},
}

INSTRUCTION_FILE_CATEGORIES = {
    "agents-md": "AGENTS.md",
    "claude-md": "CLAUDE.md",
    "gemini-md": "GEMINI.md",
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

        for category, filename in INSTRUCTION_FILE_CATEGORIES.items():
            warn_limit, error_limit = limits.get(category, (None, None))
            file_path = context.root_path / filename
            if file_path.exists():
                self._check_file(file_path, category, warn_limit, error_limit, violations)

        skill_warn, skill_error = limits.get("skill", (None, None))
        for skill_path in context.skills:
            skill_md = skill_path / "SKILL.md"
            if skill_md.exists():
                self._check_file(skill_md, "skill", skill_warn, skill_error, violations)

        command_warn, command_error = limits.get("command", (None, None))
        for plugin_path in context.plugins:
            commands_dir = plugin_path / "commands"
            if commands_dir.is_dir():
                for cmd_file in sorted(commands_dir.glob("*.md")):
                    self._check_file(cmd_file, "command", command_warn, command_error, violations)

        agent_warn, agent_error = limits.get("agent", (None, None))
        for plugin_path in context.plugins:
            agents_dir = plugin_path / "agents"
            if agents_dir.is_dir():
                for agent_file in sorted(agents_dir.glob("*.md")):
                    self._check_file(agent_file, "agent", agent_warn, agent_error, violations)

        rule_warn, rule_error = limits.get("rule", (None, None))
        for plugin_path in context.plugins:
            rules_dir = plugin_path / "rules"
            if rules_dir.is_dir():
                for rule_file in sorted(rules_dir.rglob("*.md")):
                    self._check_file(rule_file, "rule", rule_warn, rule_error, violations)

        return violations
