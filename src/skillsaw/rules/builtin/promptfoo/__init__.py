"""
Rules for validating promptfoo eval configurations.

Discovers promptfoo config files (promptfooconfig*.yaml, evals/*.yaml) and
test fragment files referenced via file://, validates their structure, and
optionally enforces assertion-type and metadata policies.
"""

from .valid import PromptfooValidRule
from .assertions import PromptfooAssertionsRule
from .metadata import PromptfooMetadataRule
from ._helpers import (
    _is_promptfoo_config,
    _resolve_file_ref,
    _extract_file_refs,
    _collect_tests,
    _get_assertion_types,
    _TestInfo,
)

__all__ = [
    "PromptfooValidRule",
    "PromptfooAssertionsRule",
    "PromptfooMetadataRule",
    # Re-exported helpers used by other modules (context.py, lint_tree.py, examples)
    "_is_promptfoo_config",
    "_resolve_file_ref",
    "_extract_file_refs",
    "_collect_tests",
    "_get_assertion_types",
    "_TestInfo",
]
