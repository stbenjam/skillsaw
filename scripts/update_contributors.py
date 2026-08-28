#!/usr/bin/env python3
"""Update README.md with the repository's human GitHub contributors."""

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

CONTRIBUTORS_START = "<!-- contributors:start -->"
CONTRIBUTORS_END = "<!-- contributors:end -->"
DEFAULT_REPOSITORY = "stbenjam/skillsaw"
GITHUB_API = "https://api.github.com"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")

# GitHub reports these automation identities as type "User", so the API's
# type field alone is insufficient to produce a human-only list.
NON_HUMAN_USERS = frozenset({"claude", "not-stbenjam"})


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
    """Render GitHub profile links as a Markdown list."""
    return "\n".join(f"- [@{login}](https://github.com/{login})" for login in logins)


def replace_contributors(readme: str, rendered: str) -> str:
    """Replace the single generated contributor block in README content."""
    if readme.count(CONTRIBUTORS_START) != 1 or readme.count(CONTRIBUTORS_END) != 1:
        raise ValueError("README must contain exactly one contributors marker pair")

    before, remainder = readme.split(CONTRIBUTORS_START, 1)
    _, after = remainder.split(CONTRIBUTORS_END, 1)
    return f"{before}{CONTRIBUTORS_START}\n" f"{rendered}\n" f"{CONTRIBUTORS_END}{after}"


def fetch_contributors(repository: str, token: Optional[str] = None) -> list[object]:
    """Fetch every contributor page from the GitHub REST API."""
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("repository must use the owner/name form")

    contributors: list[object] = []
    page = 1
    while True:
        query = urlencode({"per_page": 100, "page": page})
        request = Request(
            f"{GITHUB_API}/repos/{repository}/contributors?{query}",
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
            raise ValueError("GitHub contributors API returned a non-list response")
        contributors.extend(page_items)
        if len(page_items) < 100:
            return contributors
        page += 1


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
        contributors = fetch_contributors(args.repository, token)
        changed = update_readme(args.readme, contributors)
    except (HTTPError, URLError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    status = "updated" if changed else "already up to date"
    print(f"{args.readme}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
