import io
import json
from pathlib import Path

import pytest

import scripts.update_contributors as updater
from scripts.update_contributors import (
    CONTRIBUTORS_END,
    CONTRIBUTORS_START,
    human_logins,
    render_contributors,
    replace_contributors,
    update_readme,
)


def test_human_logins_excludes_bots_and_known_ai_accounts():
    contributors = [
        {"login": "z-human", "type": "User"},
        {"login": "github-actions[bot]", "type": "Bot"},
        {"login": "claude", "type": "User"},
        {"login": "not-stbenjam", "type": "User"},
        {"login": "A-human", "type": "User"},
        {"login": "z-human", "type": "User"},
        {"login": None, "type": "User"},
        {"login": "bad](https://example.com)", "type": "User"},
        "unexpected",
    ]

    assert human_logins(contributors) == ["A-human", "z-human"]


def test_render_contributors_links_each_github_profile():
    assert render_contributors(["alice", "bob"]) == (
        "- [@alice](https://github.com/alice)\n" "- [@bob](https://github.com/bob)"
    )


def test_replace_contributors_changes_only_the_generated_block():
    original = f"# Project\n\nBefore\n{CONTRIBUTORS_START}\n" f"- old\n{CONTRIBUTORS_END}\nAfter\n"

    assert replace_contributors(original, "- new") == (
        f"# Project\n\nBefore\n{CONTRIBUTORS_START}\n" f"- new\n{CONTRIBUTORS_END}\nAfter\n"
    )


@pytest.mark.parametrize(
    "content",
    [
        "no markers",
        f"{CONTRIBUTORS_START}\nmissing end",
        f"{CONTRIBUTORS_START}\n{CONTRIBUTORS_END}\n{CONTRIBUTORS_END}",
    ],
)
def test_replace_contributors_requires_one_marker_pair(content):
    with pytest.raises(ValueError, match="exactly one"):
        replace_contributors(content, "- new")


def test_update_readme_is_idempotent(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text(
        f"Thanks\n{CONTRIBUTORS_START}\n{CONTRIBUTORS_END}\n",
        encoding="utf-8",
    )
    contributors = [{"login": "alice", "type": "User"}]

    assert update_readme(readme, contributors) is True
    assert update_readme(readme, contributors) is False


def test_fetch_contributors_paginates_and_authenticates(monkeypatch):
    pages = [
        [{"login": f"human-{index}", "type": "User"} for index in range(100)],
        [{"login": "last-human", "type": "User"}],
    ]
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return io.BytesIO(json.dumps(pages[len(requests) - 1]).encode())

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)

    contributors = updater.fetch_contributors("owner/repo", "secret-token")

    assert contributors == pages[0] + pages[1]
    assert [request.full_url.rsplit("page=", 1)[1] for request, _ in requests] == [
        "1",
        "2",
    ]
    assert all(timeout == 30 for _, timeout in requests)
    assert all(
        request.get_header("Authorization") == "Bearer secret-token" for request, _ in requests
    )


def test_fetch_contributors_rejects_invalid_repository():
    with pytest.raises(ValueError, match="owner/name"):
        updater.fetch_contributors("not a repository")
