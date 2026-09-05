"""Rust-regex controls verified independently with rg and Grok inspection."""

from __future__ import annotations

import pytest

from skillsaw.rules.builtin.utils import _to_python_regex, rust_matcher_error

VALID = [
    "\\u{42}ash",
    "\\U{42}ash",
    "\\u{28}Bash",
    "\\U{28}Bash",
    "Bash|(?i)Write",
    "(?-u:\\w+)",
    "(?U).*",
    "\\x{42}ash",
    "(?R)^Bash$",
    "(?i-m:Write)",
    "\\x{28}Bash",
    "(?U)(Bash|Write)",
    "(?x)Bash # (?=literal comment\n",
]
INVALID = [
    "\\u{110000}",
    "\\U{110000}",
    "\\u{d800}",
    "\\U{d800}",
    "\\u{42}(",
    "\\U{42}(",
    "Bash(",
    "(?=Bash)",
    "(?U)(Bash",
    "(?-u:[a-z)",
    "\\x{110000}",
    "\\x{d800}",
    "\\x{}",
    "\\x{42}(",
]


@pytest.mark.parametrize("pattern", VALID)
def test_supported_rust_flags_and_braced_hex_do_not_warn(pattern):
    assert rust_matcher_error(pattern) is None


@pytest.mark.parametrize("pattern", INVALID)
def test_invalid_structure_is_still_checked_after_translation(pattern):
    assert rust_matcher_error(pattern) is not None


@pytest.mark.parametrize(
    "pattern", [r"\(\?U\)", "[(?U)]", r"\\x{42}ash", r"\\u{42}ash", r"\\U{42}ash"]
)
def test_literal_flag_and_escape_text_is_not_rewritten(pattern):
    assert _to_python_regex(pattern) == pattern
    assert rust_matcher_error(pattern) is None


def test_extended_mode_is_unresolved_even_when_structure_looks_invalid():
    # No Rust parser is shipped; comments change what apparent delimiters mean.
    assert rust_matcher_error("(?x)(") is None
