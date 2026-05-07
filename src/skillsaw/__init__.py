"""
skillsaw - A configurable linter for agent skills, plugins, and AI coding assistant context
"""

__version__ = "0.4.0"

from .rule import Rule, RuleViolation, Severity
from .context import RepositoryContext

__all__ = [
    "__version__",
    "Rule",
    "RuleViolation",
    "Severity",
    "RepositoryContext",
]
