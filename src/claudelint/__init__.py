"""
claudelint - backward compatibility shim for agentlint

This package has been renamed to 'agentlint'. All imports are re-exported
from the new package name. Please update your imports to use 'agentlint'.
"""

from agentlint import Rule, RuleViolation, Severity, RepositoryContext, __version__

__all__ = [
    "__version__",
    "Rule",
    "RuleViolation",
    "Severity",
    "RepositoryContext",
]
