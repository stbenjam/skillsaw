"""
skillsaw - A configurable linter for agent skills, plugins, and AI coding assistant context
"""

__version__ = "0.7.2"

from .rule import Rule, RuleViolation, Severity, AutofixConfidence, AutofixResult
from .context import RepositoryContext
from .linter import Linter

__all__ = [
    "__version__",
    "AutofixConfidence",
    "AutofixResult",
    "Linter",
    "Rule",
    "RuleViolation",
    "Severity",
    "RepositoryContext",
]
