"""
skillsaw - A configurable linter for agent skills, plugins, and AI coding assistant context
"""

from typing import TYPE_CHECKING

__version__ = "0.20.0"

# The public names, resolved on first attribute access (PEP 562).
#
# Importing them eagerly means that anything touching ``skillsaw`` — the
# CLI's argument parser included — pays for the rule base class, repository
# discovery, both YAML parsers and the linter before it knows whether the
# user asked for ``lint`` or ``--help``. The names below behave exactly as
# before once accessed; only the moment of import moves.
_LAZY_EXPORTS = {
    "AutofixConfidence": ".rule",
    "AutofixResult": ".rule",
    "Linter": ".linter",
    "RepositoryContext": ".context",
    "Rule": ".rule",
    "RuleViolation": ".rule",
    "Severity": ".rule",
}

if TYPE_CHECKING:  # keep the names visible to type checkers and IDEs
    from .context import RepositoryContext
    from .linter import Linter
    from .rule import AutofixConfidence, AutofixResult, Rule, RuleViolation, Severity

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


def __getattr__(name: str):
    """Resolve one of the public names on first access (PEP 562).

    The import happens here rather than at module scope so that naming the
    package does not pull in the linter; see ``_LAZY_EXPORTS``.
    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value  # subsequent lookups skip this hook entirely
    return value


def __dir__():
    """The public names, whether or not they have been resolved yet."""
    return sorted(__all__)
