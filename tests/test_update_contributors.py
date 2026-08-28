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
    """Only unique human GitHub accounts should survive filtering."""
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
    """Each table cell should link its handle to the matching GitHub profile."""
    assert render_contributors(["alice", "bob"]) == "\n".join(
        [
            '<table width="100%">',
            "  <tr>",
            '    <th colspan="4" align="left">Contributors</th>',
            "  </tr>",
            "  <tr>",
            '    <td width="25%"><a href="https://github.com/alice"><code>@alice</code></a></td>',
            '    <td width="25%"><a href="https://github.com/bob"><code>@bob</code></a></td>',
            '    <td width="25%"></td>',
            '    <td width="25%"></td>',
            "  </tr>",
            "</table>",
        ]
    )


def test_render_contributors_wraps_after_four_columns():
    """Contributor tables should wrap and pad rows at four columns."""
    rendered = render_contributors(["one", "two", "three", "four", "five"])

    assert rendered.count("  <tr>") == 3
    assert rendered.count('<td width="25%">') == 8
    assert '<a href="https://github.com/five"><code>@five</code></a>' in rendered


def test_replace_contributors_changes_only_the_generated_block():
    """Replacement should preserve all text outside the marker pair."""
    original = f"# Project\n\nBefore\n{CONTRIBUTORS_START}\n" f"- old\n{CONTRIBUTORS_END}\nAfter\n"

    assert replace_contributors(original, "- new") == (
        f"# Project\n\nBefore\n{CONTRIBUTORS_START}\n" f"- new\n{CONTRIBUTORS_END}\nAfter\n"
    )


def test_replace_contributors_ignores_marker_examples_in_fences():
    """Fenced marker examples should not affect the generated block lookup."""
    original = (
        f"```markdown\n{CONTRIBUTORS_START}\n{CONTRIBUTORS_END}\n```\n"
        f"Before\n{CONTRIBUTORS_START}\nold\n{CONTRIBUTORS_END}\nAfter\n"
    )

    updated = replace_contributors(original, "new")

    assert updated.startswith(
        f"```markdown\n{CONTRIBUTORS_START}\n{CONTRIBUTORS_END}\n```\nBefore\n"
    )
    assert updated.endswith(f"{CONTRIBUTORS_START}\nnew\n{CONTRIBUTORS_END}\nAfter\n")


@pytest.mark.parametrize(
    "content",
    [
        "no markers",
        f"{CONTRIBUTORS_START}\nmissing end",
        f"{CONTRIBUTORS_START}\n{CONTRIBUTORS_END}\n{CONTRIBUTORS_END}",
    ],
)
def test_replace_contributors_requires_one_marker_pair(content):
    """Missing or duplicate structural markers should fail closed."""
    with pytest.raises(ValueError, match="exactly one"):
        replace_contributors(content, "- new")


def test_update_readme_is_idempotent(tmp_path: Path):
    """A second update should leave the first result byte-for-byte intact."""
    readme = tmp_path / "README.md"
    readme.write_text(
        f"Thanks\n{CONTRIBUTORS_START}\n{CONTRIBUTORS_END}\n",
        encoding="utf-8",
    )
    contributors = [{"login": "alice", "type": "User"}]

    assert update_readme(readme, contributors) is True
    first_update = readme.read_text(encoding="utf-8")
    assert update_readme(readme, contributors) is False
    assert readme.read_text(encoding="utf-8") == first_update
    assert first_update.startswith(f"Thanks\n{CONTRIBUTORS_START}\n")
    assert first_update.endswith(f"{CONTRIBUTORS_END}\n")


def test_fetch_contributors_paginates_and_authenticates(monkeypatch):
    """API collection should authenticate and continue across full pages."""
    pages = [
        [{"login": f"human-{index}", "type": "User"} for index in range(100)],
        [{"login": "last-human", "type": "User"}],
    ]
    requests = []

    def fake_urlopen(request, timeout):
        """Return deterministic pages while recording request metadata."""
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
    """Repository input should be restricted to a safe owner/name value."""
    with pytest.raises(ValueError, match="owner/name"):
        updater.fetch_contributors("not a repository")
