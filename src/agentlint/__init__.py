"""
agentlint - backward compatibility shim for skillsaw

This package has been renamed to 'skillsaw'. All imports are re-exported
from the new package name. Please update your imports to use 'skillsaw'.
"""

from skillsaw import Rule, RuleViolation, Severity, RepositoryContext, __version__

__all__ = [
    "__version__",
    "Rule",
    "RuleViolation",
    "Severity",
    "RepositoryContext",
]
