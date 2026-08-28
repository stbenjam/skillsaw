"""Update README.md with the repository's human GitHub community contributors."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from skillsaw.markdown_doc import MarkdownDoc

CONTRIBUTORS_START = "<!-- contributors:start -->"
CONTRIBUTORS_END = "<!-- contributors:end -->"
DEFAULT_REPOSITORY = "stbenjam/skillsaw"
GITHUB_API = "https://api.github.com"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")

# GitHub reports these automation identities as type "User", so the API's
# type field alone is insufficient to produce a human-only list.
NON_HUMAN_USERS = frozenset({"claude", "not-stbenjam"})
TABLE_COLUMNS = 4


def human_logins(contributors: Iterable[object]) -> list[str]:
    """Return unique, alphabetized human logins from GitHub API records."""
    logins: set[str] = set()
    for contributor in contributors:
        if not isinstance(contributor, dict):
            continue
        login = contributor.get("login")
        account_type = contributor.get("type")
        if not isinstance(login, str) or account_type != "User" or not LOGIN_RE.fullmatch(login):
            continue
        if login.casefold() in NON_HUMAN_USERS or login.casefold().endswith("[bot]"):
            continue
        logins.add(login)
    return sorted(logins, key=str.casefold)


def render_contributors(logins: Iterable[str]) -> str:
    """Render GitHub profile links as a four-column HTML table."""
    login_list = list(logins)
    lines = [
        '<table width="100%">',
        "  <tr>",
        '    <th colspan="4" align="left">Contributors</th>',
        "  </tr>",
    ]
    for offset in range(0, len(login_list), TABLE_COLUMNS):
        row = login_list[offset : offset + TABLE_COLUMNS]
        lines.append("  <tr>")
        lines.extend(
            f'    <td width="25%"><a href="https://github.com/{login}"><code>@{login}</code></a></td>'
            for login in row
        )
        lines.extend('    <td width="25%"></td>' for _ in range(TABLE_COLUMNS - len(row)))
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def replace_contributors(readme: str, rendered: str) -> str:
    """Replace the single generated contributor block in README content."""
    doc = MarkdownDoc(readme)
    markers = {CONTRIBUTORS_START: [], CONTRIBUTORS_END: []}
    for comment in doc.html_comments():
        marker = f"<!--{comment.text}-->"
        if marker not in markers:
            continue
        line = comment.body_line_start
        if comment.body_line_end != line or doc.line(line).strip() != marker:
            raise ValueError("contributors markers must each occupy their own line")
        markers[marker].append(line)

    if any(len(lines) != 1 for lines in markers.values()):
        raise ValueError("README must contain exactly one contributors marker pair")

    start_line = markers[CONTRIBUTORS_START][0]
    end_line = markers[CONTRIBUTORS_END][0]
    if start_line >= end_line:
        raise ValueError("contributors start marker must precede the end marker")

    lines = readme.splitlines(keepends=True)
    marker_line = lines[start_line - 1]
    newline = "\r\n" if marker_line.endswith("\r\n") else "\n"
    generated = [f"{line}{newline}" for line in rendered.splitlines()]
    return "".join(lines[:start_line] + generated + lines[end_line - 1 :])


def fetch_pages(
    repository: str,
    resource: str,
    token: Optional[str] = None,
    **parameters: str,
) -> list[object]:
    """Fetch every page for a repository-scoped GitHub REST resource."""
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("repository must use the owner/name form")

    records: list[object] = []
    page = 1
    while True:
        query = urlencode({**parameters, "per_page": 100, "page": page})
        request = Request(
            f"{GITHUB_API}/repos/{repository}/{resource}?{query}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "skillsaw-contributor-updater",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        with urlopen(request, timeout=30) as response:
            page_items = json.load(response)
        if not isinstance(page_items, list):
            raise ValueError(f"GitHub {resource} API returned a non-list response")
        records.extend(page_items)
        if len(page_items) < 100:
            return records
        page += 1


def fetch_contributors(repository: str, token: Optional[str] = None) -> list[object]:
    """Fetch accounts credited by GitHub's commit contributors endpoint."""
    return fetch_pages(repository, "contributors", token)


def fetch_issue_authors(repository: str, token: Optional[str] = None) -> list[object]:
    """Fetch accounts that opened issues, excluding pull request authors."""
    records = fetch_pages(repository, "issues", token, state="all")
    return [
        record.get("user")
        for record in records
        if isinstance(record, dict) and "pull_request" not in record
    ]


def fetch_community_contributors(repository: str, token: Optional[str] = None) -> list[object]:
    """Fetch commit contributors and issue filers for the thank-you list."""
    return [
        *fetch_contributors(repository, token),
        *fetch_issue_authors(repository, token),
    ]


def update_readme(path: Path, contributors: Iterable[object]) -> bool:
    """Update the README contributor block and report whether it changed."""
    original = path.read_text(encoding="utf-8")
    rendered = render_contributors(human_logins(contributors))
    updated = replace_contributors(original, rendered)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    """Fetch contributors, update the selected README, and report status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY),
        help="GitHub repository in owner/name form",
    )
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        contributors = fetch_community_contributors(args.repository, token)
        changed = update_readme(args.readme, contributors)
    except (HTTPError, URLError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    status = "updated" if changed else "already up to date"
    print(f"{args.readme}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
