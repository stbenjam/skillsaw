"""Tests for action/review.py — GitHub PR summary comment generation."""

import re
import sys
import os

# Ensure action/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "action"))

from review import build_summary_body


def _table_data_rows(body):
    """Return only the data rows of the markdown table (skip header and separator)."""
    return [
        line
        for line in body.splitlines()
        if line.startswith("|") and "---" not in line and "Severity" not in line
    ]


class TestSummaryBodyEscaping:
    """Pipe characters and newlines in violation messages must be escaped."""

    def test_pipe_in_message_does_not_add_extra_columns(self):
        violations = [
            {
                "severity": "error",
                "rule_id": "test-rule",
                "file_path": "foo.py",
                "line": 1,
                "message": "Use A | B for the union",
            }
        ]
        body = build_summary_body(violations)
        rows = _table_data_rows(body)
        assert len(rows) == 1
        # Unescaped pipes form column boundaries; escaped ones (\|) do not.
        cols = re.split(r"(?<!\\)\|", rows[0])
        # Leading empty + 4 data cells + trailing empty = 6 parts
        assert len(cols) == 6, f"Expected 6 pipe-delimited parts, got {len(cols)}: {rows[0]}"

    def test_newline_in_message_is_replaced_with_space(self):
        violations = [
            {
                "severity": "warning",
                "rule_id": "test-rule",
                "file_path": "bar.py",
                "line": None,
                "message": "first line\nsecond line",
            }
        ]
        body = build_summary_body(violations)
        rows = _table_data_rows(body)
        assert len(rows) == 1
        assert "first line second line" in rows[0]

    def test_message_without_special_chars_unchanged(self):
        violations = [
            {
                "severity": "info",
                "rule_id": "test-rule",
                "file_path": "baz.py",
                "line": 5,
                "message": "Simple message",
            }
        ]
        body = build_summary_body(violations)
        assert "Simple message" in body

    def test_crlf_in_message_is_normalized(self):
        violations = [
            {
                "severity": "error",
                "rule_id": "test-rule",
                "file_path": "crlf.py",
                "line": 1,
                "message": "line one\r\nline two\rline three",
            }
        ]
        body = build_summary_body(violations)
        rows = _table_data_rows(body)
        assert len(rows) == 1
        assert "line one line two line three" in rows[0]

    def test_multiple_pipes_all_escaped(self):
        violations = [
            {
                "severity": "error",
                "rule_id": "test-rule",
                "file_path": "x.py",
                "line": 1,
                "message": "a|b|c",
            }
        ]
        body = build_summary_body(violations)
        rows = _table_data_rows(body)
        assert len(rows) == 1
        # The message cell should contain escaped pipes
        assert r"a\|b\|c" in rows[0]
        # And the row should still have exactly 6 pipe-delimited parts
        cols = re.split(r"(?<!\\)\|", rows[0])
        assert len(cols) == 6
