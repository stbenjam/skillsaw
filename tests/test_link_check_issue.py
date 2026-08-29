"""Tests for the dedicated link-check Action's issue reporter."""

import importlib.util
import json
from pathlib import Path
import sys
from unittest import mock

import pytest

REPORTER_PATH = Path(__file__).parents[1] / "link-check" / "report_issue.py"
SPEC = importlib.util.spec_from_file_location("link_check_report_issue", REPORTER_PATH)
assert SPEC is not None and SPEC.loader is not None
report_issue = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = report_issue
SPEC.loader.exec_module(report_issue)

SHA = "a" * 40
BASE_ENV = {
    "GITHUB_API_URL": "https://api.github.com",
    "GITHUB_REPOSITORY": "owner/repo",
    "GITHUB_RUN_ID": "1234",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_SHA": SHA,
    "GITHUB_TOKEN": "test-token",
    "SKILLSAW_ISSUE_AUTHOR": "github-actions[bot]",
    "SKILLSAW_ISSUE_TITLE": "Broken external links detected by skillsaw",
}


def _finding(path="AGENTS.md", line=7, message=None):
    return {
        "rule_id": report_issue.RULE_ID,
        "severity": "warning",
        "message": message
        or "Broken external link: [guide](https://example.com/gone) returned 404 Not Found",
        "file_path": path,
        "line": line,
        "source": "builtin",
    }


def _write_report(tmp_path, violations):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"violations": violations}), encoding="utf-8")
    return report


def _env(report):
    return {**BASE_ENV, "SKILLSAW_REPORT_FILE": str(report)}


def test_main_creates_one_managed_issue_and_escapes_untrusted_markdown(tmp_path, capsys):
    report = _write_report(
        tmp_path,
        [
            _finding(
                path="docs/a file.md",
                message=(
                    "Broken external link: [@maintainers | `oops`](https://example.com/gone) "
                    "returned 410 Gone"
                ),
            )
        ],
    )

    with mock.patch.dict("os.environ", _env(report), clear=True):
        with mock.patch.object(report_issue, "github_api", side_effect=[[], {"number": 42}]) as api:
            report_issue.main()

    assert api.call_count == 2
    method, path, payload = api.call_args_list[1].args
    assert method == "POST"
    assert path == "/repos/owner/repo/issues"
    body = payload["body"]
    assert "@maintainers" not in body
    assert "&#64;maintainers" in body
    assert "\\|" in body
    assert "docs/a%20file.md#L7" in body
    assert report_issue.ISSUE_MARKER in body
    assert "Created broken-link issue #42" in capsys.readouterr().out


def test_github_api_uses_a_bounded_timeout():
    response = mock.MagicMock()
    response.read.return_value = b"[]"
    context = mock.MagicMock()
    context.__enter__.return_value = response
    with mock.patch.dict("os.environ", BASE_ENV, clear=True):
        with mock.patch.object(
            report_issue.urllib.request, "urlopen", return_value=context
        ) as call:
            assert report_issue.github_api("GET", "/repos/owner/repo/issues") == []

    assert call.call_args.kwargs["timeout"] == report_issue.API_TIMEOUT


def test_unchanged_open_issue_is_not_edited():
    findings = [{"file_path": "AGENTS.md", "line": 7, "message": _finding()["message"]}]
    body, _fingerprint = report_issue._render_body(
        findings, "owner/repo", SHA, "1234", "https://github.com"
    )
    existing = {
        "number": 8,
        "state": "open",
        "body": body,
        "user": {"login": "github-actions[bot]"},
    }

    with mock.patch.dict("os.environ", BASE_ENV, clear=True):
        with mock.patch.object(report_issue, "_managed_issues", return_value=[existing]):
            with mock.patch.object(report_issue, "github_api") as api:
                report_issue.sync_issue(findings)

    api.assert_not_called()


def test_closed_issue_with_same_findings_is_reopened_without_replacing_body():
    findings = [{"file_path": "AGENTS.md", "line": 7, "message": _finding()["message"]}]
    body, _fingerprint = report_issue._render_body(
        findings, "owner/repo", SHA, "1234", "https://github.com"
    )
    existing = {
        "number": 9,
        "state": "closed",
        "body": body,
        "user": {"login": "github-actions[bot]"},
    }

    with mock.patch.dict("os.environ", BASE_ENV, clear=True):
        with mock.patch.object(report_issue, "_managed_issues", return_value=[existing]):
            with mock.patch.object(report_issue, "github_api") as api:
                report_issue.sync_issue(findings)

    api.assert_called_once_with("PATCH", "/repos/owner/repo/issues/9", {"state": "open"})


def test_changed_findings_update_and_reopen_the_managed_issue():
    findings = [{"file_path": "AGENTS.md", "line": 8, "message": _finding(line=8)["message"]}]
    existing = {
        "number": 10,
        "state": "closed",
        "body": "old\n<!-- skillsaw:link-check fingerprint=0000000000000000 -->",
        "user": {"login": "github-actions[bot]"},
    }

    with mock.patch.dict("os.environ", BASE_ENV, clear=True):
        with mock.patch.object(report_issue, "_managed_issues", return_value=[existing]):
            with mock.patch.object(report_issue, "github_api") as api:
                report_issue.sync_issue(findings)

    method, path, payload = api.call_args.args
    assert method == "PATCH"
    assert path == "/repos/owner/repo/issues/10"
    assert payload["state"] == "open"
    assert payload["title"] == BASE_ENV["SKILLSAW_ISSUE_TITLE"]
    assert "AGENTS.md:8" in payload["body"]


def test_no_definitive_findings_never_closes_or_edits_an_issue(tmp_path, capsys):
    report = _write_report(
        tmp_path,
        [
            {
                "rule_id": report_issue.RULE_ID,
                "severity": "info",
                "message": "Network budget exhausted before every URL was checked",
                "file_path": None,
                "line": None,
            },
            {"rule_id": "some-other-rule", "file_path": "x", "line": 1, "message": "bad"},
        ],
    )
    # GitHub credentials are deliberately absent: a no-finding run performs no
    # API operation and therefore must not need them.
    with (
        mock.patch.dict("os.environ", {"SKILLSAW_REPORT_FILE": str(report)}, clear=True),
        mock.patch.object(report_issue, "github_api") as api,
    ):
        report_issue.main()

    api.assert_not_called()
    output = capsys.readouterr().out
    assert "no issue change was made" in output
    assert "not auto-closed" in output


def test_managed_issue_lookup_requires_marker_author_and_non_pr():
    correct = {
        "number": 4,
        "state": "open",
        "body": "body\n<!-- skillsaw:link-check fingerprint=1234567890abcdef -->",
        "user": {"login": "github-actions[bot]"},
    }
    wrong_author = {**correct, "number": 3, "user": {"login": "someone"}}
    no_marker = {**correct, "number": 2, "body": "ordinary issue"}
    pull_request = {**correct, "number": 1, "pull_request": {"url": "x"}}

    with mock.patch.object(
        report_issue, "github_api", return_value=[wrong_author, no_marker, pull_request, correct]
    ):
        assert report_issue._managed_issues("owner/repo", "github-actions[bot]") == [correct]


def test_issue_body_is_bounded_and_reports_omitted_findings():
    findings = [
        {
            "file_path": f"docs/{index}.md",
            "line": index + 1,
            "message": "Broken external link: " + ("x" * 1000),
        }
        for index in range(600)
    ]
    body, _fingerprint = report_issue._render_body(
        findings, "owner/repo", SHA, "1234", "https://github.com"
    )

    assert len(body) <= report_issue.MAX_BODY_CHARS
    assert "additional finding(s) were omitted" in body
    assert body.rstrip().endswith("-->")


@pytest.mark.parametrize(
    "report_content",
    ["", "[]", '{"violations": "not-a-list"}', "{not-json"],
)
def test_invalid_reports_fail_cleanly(tmp_path, report_content, capsys):
    report = tmp_path / "report.json"
    report.write_text(report_content, encoding="utf-8")

    with (
        mock.patch.dict("os.environ", {"SKILLSAW_REPORT_FILE": str(report)}, clear=True),
        pytest.raises(SystemExit) as error,
    ):
        report_issue.main()

    assert error.value.code == 1
    assert "Could not report broken links" in capsys.readouterr().err
