"""
agentlint - A configurable linter for agent skills, Claude Code plugins, and marketplaces
"""

__version__ = "0.3.6"

from .rule import Rule, RuleViolation, Severity
from .context import RepositoryContext

__all__ = [
    "__version__",
    "Rule",
    "RuleViolation",
    "Severity",
    "RepositoryContext",
]
