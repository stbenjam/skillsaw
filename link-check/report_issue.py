"""Create or update one GitHub issue for confirmed broken external links."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode, urlsplit
import urllib.error
import urllib.request

RULE_ID = "content-broken-external-reference"
ISSUE_MARKER = "<!-- skillsaw:link-check"
FINGERPRINT_RE = re.compile(r"<!-- skillsaw:link-check fingerprint=([a-f0-9]{16}) -->")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")
RUN_ID_RE = re.compile(r"^[0-9]+$")
MAX_REPORT_BYTES = 10 * 1024 * 1024
MAX_BODY_CHARS = 60_000
MAX_FINDINGS = 500
API_TIMEOUT = 30
DEFAULT_TITLE = "Broken external links detected by skillsaw"
DEFAULT_AUTHOR = "github-actions[bot]"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _api_base() -> str:
    value = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("GITHUB_API_URL must be an HTTPS origin")
    return value


def github_api(method: str, path: str, body: Optional[Dict] = None):
    """Call GitHub's REST API using the workflow token."""
    token = _required_env("GITHUB_TOKEN")
    url = f"{_api_base()}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else None
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace") if error.fp else ""
        print(
            f"GitHub API error: {error.code} {error.reason}: {response_body}",
            file=sys.stderr,
        )
        raise


def _markdown_text(value: object) -> str:
    """Fold an untrusted scalar into inert, single-line Markdown text."""
    text = " ".join(str(value).splitlines())
    text = text.replace("&", "&amp;")
    text = text.replace("`", "&#96;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\\", "\\\\").replace("@", "&#64;")
    for character in "[]|*_~":
        text = text.replace(character, f"\\{character}")
    return text


def _markdown_code_text(value: object) -> str:
    """Fold an untrusted scalar for a backtick-delimited table cell."""
    return " ".join(str(value).splitlines()).replace("`", "&#96;").replace("|", "\\|")


def _load_findings(report_file: str) -> List[Dict]:
    path = Path(report_file)
    if not path.is_file():
        raise ValueError("The skillsaw report file is missing or is not a regular file")
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("The skillsaw report is too large to process safely")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read the skillsaw report: {error}") from error
    if not isinstance(report, dict) or not isinstance(report.get("violations"), list):
        raise ValueError("Invalid skillsaw report: 'violations' must be a list")

    findings = []
    for violation in report["violations"]:
        if not isinstance(violation, dict) or violation.get("rule_id") != RULE_ID:
            continue
        path_value = violation.get("file_path")
        message = violation.get("message")
        line = violation.get("line")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        if not isinstance(message, str) or not message.startswith("Broken external link:"):
            continue
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            continue
        findings.append(
            {
                "file_path": path_value,
                "line": line,
                "message": message,
            }
        )
    return sorted(findings, key=lambda item: (item["file_path"], item["line"], item["message"]))


def _fingerprint(findings: List[Dict]) -> str:
    encoded = json.dumps(findings, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _validated_context() -> Tuple[str, str, str, str, str, str]:
    repository = _required_env("GITHUB_REPOSITORY")
    sha = _required_env("GITHUB_SHA")
    run_id = _required_env("GITHUB_RUN_ID")
    server_url = _required_env("GITHUB_SERVER_URL").rstrip("/")
    title = os.environ.get("SKILLSAW_ISSUE_TITLE", DEFAULT_TITLE).strip()
    author = os.environ.get("SKILLSAW_ISSUE_AUTHOR", DEFAULT_AUTHOR).strip()

    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("GITHUB_REPOSITORY must have the form owner/repository")
    if not SHA_RE.fullmatch(sha):
        raise ValueError("GITHUB_SHA must be a 40- to 64-character hexadecimal commit ID")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("GITHUB_RUN_ID must be numeric")
    parsed_server = urlsplit(server_url)
    if (
        parsed_server.scheme != "https"
        or not parsed_server.netloc
        or parsed_server.username
        or parsed_server.password
        or parsed_server.path not in ("", "/")
        or parsed_server.query
        or parsed_server.fragment
    ):
        raise ValueError("GITHUB_SERVER_URL must be an HTTPS origin")
    if not title or len(title) > 256 or "\n" in title or "\r" in title:
        raise ValueError("SKILLSAW_ISSUE_TITLE must be a single line of at most 256 characters")
    if not author or any(character.isspace() for character in author):
        raise ValueError("SKILLSAW_ISSUE_AUTHOR must be a GitHub login")
    return repository, sha.lower(), run_id, server_url, title, author


def _render_body(
    findings: List[Dict], repository: str, sha: str, run_id: str, server_url: str
) -> Tuple[str, str]:
    fingerprint = _fingerprint(findings)
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"
    commit_url = f"{server_url}/{repository}/commit/{sha}"
    lines = [
        f"skillsaw confirmed {len(findings)} broken external link(s) (HTTP 404 or 410).",
        "",
        "This issue is maintained by the skillsaw link-check Action. It is not closed "
        "automatically because a later silent result can be inconclusive; close it after "
        "fixing or intentionally ignoring the reported links.",
        "",
        f"Last confirmed at [`{sha[:12]}`]({commit_url}) in [this workflow run]({run_url}).",
        "",
        "| Location | Finding |",
        "|----------|---------|",
    ]

    included = 0
    for finding in findings[:MAX_FINDINGS]:
        path = finding["file_path"]
        line = finding["line"]
        encoded_path = quote(path, safe="/")
        location_url = f"{server_url}/{repository}/blob/{sha}/{encoded_path}#L{line}"
        location = f"[`{_markdown_code_text(path)}:{line}`]({location_url})"
        row = f"| {location} | {_markdown_text(finding['message'])} |"
        reserved = 250
        if len("\n".join(lines)) + len(row) + reserved > MAX_BODY_CHARS:
            break
        lines.append(row)
        included += 1

    omitted = len(findings) - included
    if omitted:
        lines.extend(
            [
                "",
                f"{omitted} additional finding(s) were omitted from the issue; see the workflow run.",
            ]
        )
    lines.extend(["", f"<!-- skillsaw:link-check fingerprint={fingerprint} -->"])
    return "\n".join(lines), fingerprint


def _managed_issues(repository: str, author: str) -> List[Dict]:
    matches = []
    for page in range(1, 11):
        query = urlencode({"state": "all", "per_page": 100, "page": page, "creator": author})
        issues = github_api("GET", f"/repos/{repository}/issues?{query}")
        if not isinstance(issues, list):
            raise ValueError("GitHub returned an invalid issue-list response")
        for issue in issues:
            if not isinstance(issue, dict) or "pull_request" in issue:
                continue
            user = issue.get("user")
            body = issue.get("body")
            if (
                isinstance(user, dict)
                and user.get("login") == author
                and isinstance(body, str)
                and ISSUE_MARKER in body
            ):
                matches.append(issue)
        if len(issues) < 100:
            break

    def sort_key(issue: Dict) -> Tuple[bool, int]:
        number = issue.get("number")
        safe_number = number if isinstance(number, int) and not isinstance(number, bool) else 0
        return issue.get("state") == "open", safe_number

    return sorted(matches, key=sort_key, reverse=True)


def _existing_fingerprint(issue: Dict) -> Optional[str]:
    body = issue.get("body")
    if not isinstance(body, str):
        return None
    match = FINGERPRINT_RE.search(body)
    return match.group(1) if match else None


def sync_issue(findings: List[Dict]) -> None:
    repository, sha, run_id, server_url, title, author = _validated_context()
    body, fingerprint = _render_body(findings, repository, sha, run_id, server_url)
    issues = _managed_issues(repository, author)
    if len(issues) > 1:
        print(
            f"Found {len(issues)} managed issues; updating the newest open issue.",
            file=sys.stderr,
        )

    if not issues:
        created = github_api(
            "POST",
            f"/repos/{repository}/issues",
            {"title": title, "body": body},
        )
        number = created.get("number") if isinstance(created, dict) else None
        print(f"Created broken-link issue{f' #{number}' if number else ''}.")
        return

    issue = issues[0]
    number = issue.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ValueError("The managed issue has no valid issue number")
    same_findings = _existing_fingerprint(issue) == fingerprint
    is_open = issue.get("state") == "open"
    if same_findings and is_open:
        print(f"Broken-link issue #{number} already contains these findings.")
        return

    payload = {"state": "open"}
    if not same_findings:
        payload.update({"title": title, "body": body})
    github_api("PATCH", f"/repos/{repository}/issues/{number}", payload)
    verb = "Reopened" if not is_open else "Updated"
    print(f"{verb} broken-link issue #{number}.")


def main() -> None:
    try:
        report_file = _required_env("SKILLSAW_REPORT_FILE")
        findings = _load_findings(report_file)
        if not findings:
            print(
                "No confirmed broken external links; no issue change was made. "
                "Existing issues are not auto-closed because silent network results can be inconclusive."
            )
            return
        sync_issue(findings)
    except (ValueError, OSError, urllib.error.URLError) as error:
        print(f"Could not report broken links: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
