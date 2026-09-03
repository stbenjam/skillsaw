"""``grok-marketplace-index-parity`` — the display catalog and its drift.

``plugin-index.json`` is the sole source of the component listing shown
before an install. Measured against Grok Build 1.0.13: with the index ``sha``
equal to the catalog entry's, the listing carried every component; with them
different, the ``components`` block was absent, silently. For a local source
there is no ``sha`` to gate on, so an index claiming three skills won the
display over a plugin shipping one.

The rule reports nothing when there is no index, which is the documented
case and was measured harmless.
"""

from __future__ import annotations

import json

import pytest

from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokMarketplaceIndexParityRule

from tests.grok._helpers import (
    copy_fixture,
    messages,
    only,
    run_rule,
    write_catalog,
    write_plugin,
    write_repo,
)

SHA_A = "1f9d0c73a86b24e510" + "7cad3f88b90250e6c147da"
SHA_B = "70e4d2c81f6a35b09c" + "7e18d4a6f30b25ce817d94"

SKILL = (
    "---\nname: tide-window\ndescription: Find the low-tide windows long enough for a "
    "shoreline survey. Use when planning field work.\n---\n\n# Window\n\nAsk for the "
    "station id, then report each window.\n"
)


def url_entry(name: str, sha=None) -> dict:
    source = {"source": "url", "url": f"https://example.invalid/{name}.git"}
    if sha is not None:
        source["sha"] = sha
    return {"name": name, "description": f"The {name} plugin.", "source": source}


def index(plugins: dict) -> dict:
    return {"version": 1, "plugins": plugins}


def marketplace(temp_dir, name: str, catalog, index_doc, skills=()):
    """A marketplace holding *catalog*, *index_doc* and a local plugin."""
    repo = write_repo(temp_dir / name)
    write_catalog(repo, catalog)
    if index_doc is not None:
        write_catalog(repo, index_doc, filename="plugin-index.json")
    if skills:
        plugin = write_plugin(repo / "plugins" / "almanac", {"name": "almanac"})
        for skill in skills:
            (plugin / "skills" / skill).mkdir(parents=True)
            (plugin / "skills" / skill / "SKILL.md").write_text(SKILL, encoding="utf-8")
    return repo


def check(repo, config=None):
    return run_rule(GrokMarketplaceIndexParityRule, repo, config)


@pytest.fixture
def broken(tmp_path):
    return copy_fixture("grok/marketplace-broken", tmp_path)


# ── No index at all ──────────────────────────────────────────────


def test_an_absent_index_reports_nothing(temp_dir) -> None:
    repo = marketplace(temp_dir, "no-index", {"plugins": [url_entry("almanac", SHA_A)]}, None)

    assert check(repo) == []


# ── Names ────────────────────────────────────────────────────────


def test_a_name_missing_from_the_index_is_reported(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "missing-name",
        {"plugins": [url_entry("almanac", SHA_A), url_entry("tides", SHA_B)]},
        index({"almanac": {"sha": SHA_A}}),
    )

    found = only(check(repo), "disagrees")

    assert found.severity == Severity.WARNING
    assert "not in the index: tides" in found.message


def test_a_name_only_the_index_carries_is_reported(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "ghost-name",
        {"plugins": [url_entry("almanac", SHA_A)]},
        index({"almanac": {"sha": SHA_A}, "retired": {"sha": SHA_B}}),
    )

    assert "not in the catalog: retired" in only(check(repo), "disagrees").message


def test_the_resolved_manifest_name_also_matches(temp_dir) -> None:
    """An index generated from the resolved names must not read as drift
    against a catalog whose entry names differ."""
    repo = write_repo(temp_dir / "resolved-match")
    write_catalog(repo, {"plugins": [{"name": "harbour-almanac", "source": "./plugins/almanac"}]})
    write_plugin(repo / "plugins" / "almanac", {"name": "almanac"})
    write_catalog(repo, index({"almanac": {}}), filename="plugin-index.json")

    assert check(repo) == []


# ── The pin ──────────────────────────────────────────────────────


def test_a_sha_that_disagrees_is_reported(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "drifted",
        {"plugins": [url_entry("almanac", SHA_A)]},
        index({"almanac": {"sha": SHA_B}}),
    )

    assert "'sha' differs: almanac" in only(check(repo), "disagrees").message


def test_a_sha_that_differs_only_in_case_is_not_drift(temp_dir) -> None:
    """The installer treats a commit id case-insensitively, and the casing
    is grok-marketplace-json-valid's finding, not a second one here."""
    repo = marketplace(
        temp_dir,
        "case-only",
        {"plugins": [url_entry("almanac", SHA_A)]},
        index({"almanac": {"sha": SHA_A.upper()}}),
    )

    assert check(repo) == []


@pytest.mark.parametrize(
    "catalog_sha,index_entry,expected",
    [
        pytest.param(SHA_A, {}, "'sha' in the catalog only", id="catalog-only"),
        pytest.param(None, {"sha": SHA_A}, "'sha' in the index only", id="index-only"),
    ],
)
def test_a_sha_on_one_side_only_is_reported(temp_dir, catalog_sha, index_entry, expected) -> None:
    repo = marketplace(
        temp_dir,
        f"one-sided-{expected[-6:]}",
        {"plugins": [url_entry("almanac", catalog_sha)]},
        index({"almanac": index_entry}),
    )

    assert expected in only(check(repo), "disagrees").message


# ── Components, for local sources only ───────────────────────────


def test_skills_the_index_claims_and_the_plugin_lacks_are_reported(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "component-drift",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index(
            {
                "almanac": {
                    "components": {"skills": [{"name": "tide-window"}, {"name": "ebb-window"}]}
                }
            }
        ),
        skills=("tide-window",),
    )

    assert (
        "skills only the index lists: almanac/ebb-window" in only(check(repo), "disagrees").message
    )


def test_skills_the_plugin_ships_and_the_index_omits_are_reported(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "index-behind",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index({"almanac": {"components": {"skills": [{"name": "tide-window"}]}}}),
        skills=("tide-window", "ebb-window"),
    )

    assert (
        "skills only the plugin ships: almanac/ebb-window" in only(check(repo), "disagrees").message
    )


def test_check_components_off_keeps_the_name_and_sha_checks(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "components-off",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index(
            {
                "almanac": {"components": {"skills": [{"name": "ebb-window"}]}},
                "retired": {},
            }
        ),
        skills=("tide-window",),
    )

    message = only(check(repo, {"check-components": False}), "disagrees").message

    assert "skills only" not in message
    assert "not in the catalog: retired" in message


def test_a_matching_index_reports_nothing(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "in-step",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index({"almanac": {"components": {"skills": [{"name": "tide-window"}]}}}),
        skills=("tide-window",),
    )

    assert check(repo) == []


# ── An index Grok ignores ────────────────────────────────────────


def test_a_malformed_index_is_one_finding(temp_dir) -> None:
    repo = marketplace(temp_dir, "bad-index", {"plugins": [url_entry("almanac", SHA_A)]}, index({}))
    (repo / ".grok-plugin" / "plugin-index.json").write_text('{"plugins": {,}}', encoding="utf-8")

    found = check(repo)

    assert len(found) == 1
    assert "Invalid JSON" in found[0].message


def test_an_index_whose_plugins_is_not_an_object_is_one_finding(temp_dir) -> None:
    repo = marketplace(
        temp_dir, "list-index", {"plugins": [url_entry("almanac", SHA_A)]}, index([])
    )

    assert messages(check(repo)) == ["'plugins' must be an object keyed by plugin name"]


def test_an_unreadable_catalog_reports_no_parity(temp_dir) -> None:
    """One defect, one finding: grok-marketplace-json-valid names the
    catalog, and comparing against nothing would report every plugin."""
    repo = marketplace(temp_dir, "bad-catalog", {"plugins": []}, index({"almanac": {"sha": SHA_A}}))
    (repo / ".grok-plugin" / "marketplace.json").write_text('{"plugins": [,]}', encoding="utf-8")

    assert check(repo) == []


# ── An index Grok never reads ────────────────────────────────────


@pytest.mark.parametrize("location", ["plugin-index.json", ".claude-plugin/plugin-index.json"])
def test_an_index_away_from_its_catalog_is_reported(temp_dir, location) -> None:
    repo = marketplace(temp_dir, f"stray-{len(location)}", {"plugins": []}, None)
    stray = repo / location
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text(json.dumps(index({"almanac": {}})), encoding="utf-8")

    found = check(repo)

    assert len(found) == 1
    assert "is not beside '.grok-plugin/marketplace.json'" in found[0].message
    assert found[0].file_path == stray


# ── Fixtures ─────────────────────────────────────────────────────


def test_the_broken_fixture_is_one_consolidated_finding(broken) -> None:
    found = check(broken)

    assert len(found) == 1
    message = found[0].message
    assert "not in the index" in message
    assert "not in the catalog: retired" in message
    assert "'sha' differs: drifted" in message
    assert "skills only the index lists: current-log/ebb-window" in message


def test_the_clean_fixture_reports_nothing(tmp_path) -> None:
    assert check(copy_fixture("grok/marketplace-clean", tmp_path)) == []
