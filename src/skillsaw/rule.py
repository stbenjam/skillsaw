"""
Base classes for linting rules
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import RepositoryContext


class Severity(Enum):
    """Rule violation severity levels"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AutofixConfidence(Enum):
    SAFE = "safe"
    SUGGEST = "suggest"
    LLM = "llm"


@dataclass
class RuleViolation:
    """Represents a rule violation"""

    rule_id: str
    severity: Severity
    message: str
    file_path: Optional[Path] = None
    line: Optional[int] = None

    def __str__(self):
        """Format violation for display"""
        icon = {Severity.ERROR: "✗", Severity.WARNING: "⚠", Severity.INFO: "ℹ"}[self.severity]

        location = ""
        if self.file_path:
            location = f" [{self.file_path}]"
            if self.line:
                location = f" [{self.file_path}:{self.line}]"

        return f"{icon} {self.severity.value.upper()}{location}: {self.message}"


@dataclass
class AutofixResult:
    rule_id: str
    file_path: Path
    confidence: AutofixConfidence
    original_content: str
    fixed_content: str
    description: str
    violations_fixed: List[RuleViolation] = field(default_factory=list)
    rename_from: Optional[Path] = None


class Rule(ABC):
    """Base class for linting rules"""

    repo_types = None
    formats = None
    config_schema = {}
    since = "0.1.0"

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize rule with optional configuration

        Args:
            config: Rule-specific configuration from .skillsaw.yaml
        """
        self.config = config or {}
        self._enabled = self.config.get("enabled", True)

        # Get severity from config or use default
        severity_str = self.config.get("severity", self.default_severity().value)
        if severity_str is None:
            self._severity = self.default_severity()
        else:
            try:
                self._severity = Severity(severity_str)
            except (ValueError, KeyError, TypeError) as err:
                valid = ", ".join(s.value for s in Severity)
                raise ValueError(
                    f"Invalid severity '{severity_str}' for rule '{self.rule_id}'. "
                    f"Valid values: {valid}"
                ) from err

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique identifier for this rule (e.g., 'plugin-json-required')"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this rule checks"""
        pass

    @abstractmethod
    def default_severity(self) -> Severity:
        """Default severity level for this rule"""
        pass

    @property
    def enabled(self) -> bool:
        """Check if rule is enabled"""
        return self._enabled

    @property
    def severity(self) -> Severity:
        """Get configured severity level"""
        return self._severity

    @abstractmethod
    def check(self, context: "RepositoryContext") -> List[RuleViolation]:
        """
        Execute the rule check

        Args:
            context: Repository context with paths and metadata

        Returns:
            List of violations found
        """
        pass

    def fix(
        self,
        context: "RepositoryContext",
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        """
        Attempt to fix violations found by check().

        Override in subclasses to provide autofix capability.
        Rules without a fix() override continue to work — this default
        returns an empty list.
        """
        return []

    @property
    def supports_autofix(self) -> bool:
        return type(self).fix is not Rule.fix

    @property
    def llm_fix_prompt(self) -> Optional[str]:
        return None

    def violation(
        self,
        message: str,
        file_path: Path = None,
        line: int = None,
        severity: Severity = None,
    ) -> RuleViolation:
        """
        Create a violation for this rule

        Args:
            message: Violation message
            file_path: Optional file path where violation occurred
            line: Optional line number
            severity: Override severity (defaults to rule's configured severity)

        Returns:
            RuleViolation instance
        """
        return RuleViolation(
            rule_id=self.rule_id,
            severity=severity if severity is not None else self.severity,
            message=message,
            file_path=file_path,
            line=line,
        )
