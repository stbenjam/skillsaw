"""Rust-regex controls verified independently with rg and Grok inspection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsaw.rules.builtin.utils import _to_python_regex, rust_matcher_error

EVIDENCE_PATH = Path(__file__).parent / "fixtures" / "hooks" / "rust-matchers" / "evidence.json"
CASES = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_pinned_matcher_diagnostics(case):
    # A missing finding can mean abstention; native verdicts are separate evidence.
    error = rust_matcher_error(case["pattern"])
    assert ("warning" if error is not None else None) == case["skillsaw_finding"]


@pytest.mark.parametrize(
    "pattern", [r"\(\?U\)", "[(?U)]", r"\\x{42}ash", r"\\u{42}ash", r"\\U{42}ash"]
)
def test_literal_flag_and_escape_text_is_not_rewritten(pattern):
    assert _to_python_regex(pattern) == pattern
    assert rust_matcher_error(pattern) is None
