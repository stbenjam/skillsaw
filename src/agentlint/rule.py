"""
Base classes for linting rules
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
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


class Rule(ABC):
    """Base class for linting rules"""

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize rule with optional configuration

        Args:
            config: Rule-specific configuration from .agentlint.yaml
        """
        self.config = config or {}
        self._enabled = self.config.get("enabled", True)

        # Get severity from config or use default
        severity_str = self.config.get("severity", self.default_severity().value)
        self._severity = Severity(severity_str)

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
