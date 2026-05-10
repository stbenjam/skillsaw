"""
Tests for the claudelint backward-compatibility shim.

Every public symbol exported by skillsaw must also be importable from claudelint.
"""

import skillsaw


def test_claudelint_exports_match_skillsaw():
    """All symbols in skillsaw.__all__ must be importable from claudelint."""
    import claudelint

    for name in skillsaw.__all__:
        assert hasattr(claudelint, name), f"claudelint shim is missing export: {name}"


def test_import_autofix_symbols():
    """AutofixConfidence and AutofixResult are importable from claudelint."""
    from claudelint import AutofixConfidence, AutofixResult

    assert AutofixConfidence is skillsaw.AutofixConfidence
    assert AutofixResult is skillsaw.AutofixResult


def test_import_core_symbols():
    """Core symbols are importable from claudelint."""
    from claudelint import Linter, Rule, RuleViolation, Severity, RepositoryContext

    assert Linter is skillsaw.Linter
    assert Rule is skillsaw.Rule
    assert RuleViolation is skillsaw.RuleViolation
    assert Severity is skillsaw.Severity
    assert RepositoryContext is skillsaw.RepositoryContext
