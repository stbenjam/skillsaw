"""
skillsaw - A configurable linter for agent skills, plugins, and AI coding assistant context
"""

__version__ = "0.4.0"

from .rule import Rule, RuleViolation, Severity
from .context import RepositoryContext
from .linter import Linter

__all__ = [
    "__version__",
    "Linter",
    "Rule",
    "RuleViolation",
    "Severity",
    "RepositoryContext",
]
