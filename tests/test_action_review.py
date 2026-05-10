"""Tests for action/review.py crash-path guards."""

import json
import os
import sys
from unittest import mock

import pytest

# action/ is not a package, so we import it by manipulating sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "action"))
import review  # noqa: E402


class TestReportFileGuards:
    """Guards around the SKILLSAW_REPORT_FILE path."""

    def test_missing_report_file_skips(self, capsys):
        """main() returns early when SKILLSAW_REPORT_FILE points to nothing."""
        with mock.patch.dict(os.environ, {"SKILLSAW_REPORT_FILE": "/nonexistent"}):
            review.main()
        assert "No skillsaw report found" in capsys.readouterr().err

    def test_directory_as_report_file_skips(self, tmp_path, capsys):
        """main() returns early when SKILLSAW_REPORT_FILE is a directory."""
        d = tmp_path / "reports"
        d.mkdir()
        with mock.patch.dict(os.environ, {"SKILLSAW_REPORT_FILE": str(d)}):
            review.main()
        assert "No skillsaw report found" in capsys.readouterr().err

    def test_empty_report_file_skips(self, tmp_path, capsys):
        """main() returns early when the report file is empty."""
        f = tmp_path / "report.json"
        f.write_text("")
        with mock.patch.dict(os.environ, {"SKILLSAW_REPORT_FILE": str(f)}):
            review.main()
        assert "Report file is empty" in capsys.readouterr().err


class TestMissingEnvVars:
    """Missing GITHUB_REPOSITORY / PR_NUMBER / HEAD_SHA should give a
    clear error, not a raw KeyError."""

    def _write_report(self, tmp_path, violations=None):
        f = tmp_path / "report.json"
        f.write_text(
            json.dumps(
                {
                    "violations": violations
                    or [
                        {
                            "file_path": "a.py",
                            "severity": "error",
                            "rule_id": "R1",
                            "message": "bad",
                        }
                    ]
                }
            )
        )
        return str(f)

    def test_all_missing(self, tmp_path):
        report = self._write_report(tmp_path)
        env = {"SKILLSAW_REPORT_FILE": report, "GITHUB_TOKEN": "t"}
        # Remove the three required vars if they exist
        clean = {
            k: v
            for k, v in os.environ.items()
            if k not in ("GITHUB_REPOSITORY", "PR_NUMBER", "HEAD_SHA")
        }
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                review.main()
            assert exc_info.value.code == 1

    def test_partial_missing(self, tmp_path, capsys):
        report = self._write_report(tmp_path)
        env = {
            "SKILLSAW_REPORT_FILE": report,
            "GITHUB_TOKEN": "t",
            "GITHUB_REPOSITORY": "owner/repo",
        }
        clean = {k: v for k, v in os.environ.items() if k not in ("PR_NUMBER", "HEAD_SHA")}
        clean.update(env)
        with mock.patch.dict(os.environ, clean, clear=True):
            with pytest.raises(SystemExit):
                review.main()
        err = capsys.readouterr().err
        assert "PR_NUMBER" in err
        assert "HEAD_SHA" in err
        # GITHUB_REPOSITORY is present, so it should not appear in the error
        assert "GITHUB_REPOSITORY" not in err


class TestMalformedViolations:
    """Violations missing rule_id, message, or severity must not crash."""

    def test_violation_missing_rule_id_and_message(self, tmp_path):
        """A violation dict with no rule_id/message should use defaults."""
        report_path = tmp_path / "report.json"
        report_path.write_text(
            json.dumps(
                {
                    "violations": [
                        {"file_path": "foo.py", "severity": "error"},
                    ]
                }
            )
        )
        env = {
            "SKILLSAW_REPORT_FILE": str(report_path),
            "GITHUB_TOKEN": "t",
            "GITHUB_REPOSITORY": "owner/repo",
            "PR_NUMBER": "1",
            "HEAD_SHA": "abc123",
        }
        diff_files = {"foo.py"}
        diff_lines = {("foo.py", 10)}
        with mock.patch.dict(os.environ, env):
            with mock.patch.object(review, "get_diff_info", return_value=(diff_files, diff_lines)):
                with mock.patch.object(review, "sync_comments", return_value=[]):
                    with mock.patch.object(review, "upsert_summary_comment"):
                        # Should not raise
                        review.main()

    def test_violation_missing_severity(self, tmp_path):
        """A violation with no severity falls back to 'warning'."""
        report_path = tmp_path / "report.json"
        report_path.write_text(
            json.dumps(
                {
                    "violations": [
                        {"file_path": "bar.py", "rule_id": "R1", "message": "oops"},
                    ]
                }
            )
        )
        env = {
            "SKILLSAW_REPORT_FILE": str(report_path),
            "GITHUB_TOKEN": "t",
            "GITHUB_REPOSITORY": "owner/repo",
            "PR_NUMBER": "1",
            "HEAD_SHA": "abc123",
        }
        diff_files = {"bar.py"}
        diff_lines = set()
        captured_comments = []

        def fake_sync(repo, pr, comments):
            captured_comments.extend(comments)
            return comments

        with mock.patch.dict(os.environ, env):
            with mock.patch.object(review, "get_diff_info", return_value=(diff_files, diff_lines)):
                with mock.patch.object(review, "sync_comments", side_effect=fake_sync):
                    with mock.patch.object(review, "upsert_summary_comment"):
                        with mock.patch.object(review, "github_api"):
                            review.main()

        assert len(captured_comments) == 1
        assert "warning" in captured_comments[0]["body"]

    def test_summary_table_with_missing_keys(self):
        """upsert_summary_comment must not crash on sparse violation dicts."""
        violations = [
            {"severity": "error", "file_path": "x.py"},
            {"file_path": "y.py"},
            {},
        ]
        with mock.patch.object(review, "github_api") as api:
            api.return_value = []  # no existing comments
            review.upsert_summary_comment("o/r", "1", violations)
        # The POST call should have been made without crashing
        assert api.call_count == 2  # one GET page, one POST
