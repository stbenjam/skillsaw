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

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import GrokMarketplaceConfigNode, GrokMarketplaceIndexNode
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


def skill_doc(name: str) -> str:
    """A SKILL.md whose frontmatter name is *name*.

    Declared per skill rather than shared: the generator writes the
    frontmatter name into the index, so two directories sharing one would
    ship one name between them.
    """
    return (
        f"---\nname: {name}\ndescription: Find the low-tide windows long enough for a "
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


def marketplace(temp_dir, name: str, catalog, index_doc, skills=(), manifest=None):
    """A marketplace holding *catalog*, *index_doc* and a local plugin.

    Each entry in *skills* is a directory name, or a
    ``(directory, frontmatter name)`` pair when the two differ.
    """
    repo = write_repo(temp_dir / name)
    write_catalog(repo, {"name": "harbour-plugins", **catalog})
    if index_doc is not None:
        write_catalog(repo, index_doc, filename="plugin-index.json")
    if skills or manifest:
        plugin = write_plugin(repo / "plugins" / "almanac", manifest or {"name": "almanac"})
        for skill in skills:
            directory, declared = skill if isinstance(skill, tuple) else (skill, skill)
            target = plugin / "skills" / directory
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text(skill_doc(declared), encoding="utf-8")
    return repo


def check(repo, config=None):
    return run_rule(GrokMarketplaceIndexParityRule, repo, config)


@pytest.fixture
def broken(tmp_path):
    repo = copy_fixture("grok/marketplace-broken", tmp_path)
    # Exercise parity only after the whole catalog passes typed decoding.
    path = repo / ".grok-plugin/marketplace.json"
    data = json.loads(path.read_text())
    data["plugins"][7]["source"]["sha"] = SHA_A
    data["plugins"][10]["name"] = "wind-fetch"
    path.write_text(json.dumps(data))
    return repo


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


def test_the_resolved_manifest_name_is_not_a_display_index_key(temp_dir) -> None:
    """The listing name and the component lookup key are separate."""
    repo = write_repo(temp_dir / "resolved-match")
    write_catalog(
        repo,
        {
            "name": "harbour-plugins",
            "plugins": [{"name": "harbour-almanac", "source": "./plugins/almanac"}],
        },
    )
    write_plugin(repo / "plugins/almanac", {"name": "almanac"})
    write_catalog(repo, index({"almanac": {"components": {}}}), filename="plugin-index.json")

    assert messages(check(repo)) == [
        "plugin-index.json disagrees with marketplace.json: "
        "not in the index: harbour-almanac; not in the catalog: almanac"
    ]


# ── The pin ──────────────────────────────────────────────────────


def test_a_sha_that_disagrees_is_reported(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "drifted",
        {"plugins": [url_entry("almanac", SHA_A)]},
        index({"almanac": {"sha": SHA_B}}),
    )

    assert "'sha' differs: almanac" in only(check(repo), "disagrees").message


def test_a_sha_that_differs_only_in_case_is_display_drift(temp_dir) -> None:
    """Display lookup compares stored strings, independently of installation."""
    repo = marketplace(
        temp_dir,
        "case-only",
        {"plugins": [url_entry("almanac", SHA_A)]},
        index({"almanac": {"sha": SHA_A.upper()}}),
    )

    assert "'sha' differs: almanac" in only(check(repo), "disagrees").message


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


def test_a_skill_nested_under_the_conventional_directory_is_walked(temp_dir) -> None:
    """Measured against 1.0.13: the walk is recursive, so a skill several
    directories down is one the plugin ships and an index omitting it has
    drifted."""
    repo = marketplace(
        temp_dir,
        "nested-skill",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index({"almanac": {"components": {"skills": []}}}),
        manifest={"name": "almanac"},
    )
    nested = repo / "plugins" / "almanac" / "skills" / "coastal" / "ebb-window"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(skill_doc("ebb-window"), encoding="utf-8")

    assert (
        "skills only the plugin ships: almanac/ebb-window" in only(check(repo), "disagrees").message
    )


def test_a_declared_path_that_is_itself_a_skill_is_walked(temp_dir) -> None:
    """Measured: a declared root holding its own ``SKILL.md`` is a skill, not
    merely a folder of them."""
    repo = marketplace(
        temp_dir,
        "declared-is-a-skill",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index({"almanac": {"components": {"skills": [{"name": "ebb-window"}]}}}),
        manifest={"name": "almanac", "skills": ["./bundled/ebb-window"]},
    )
    declared = repo / "plugins" / "almanac" / "bundled" / "ebb-window"
    declared.mkdir(parents=True)
    (declared / "SKILL.md").write_text(skill_doc("ebb-window"), encoding="utf-8")

    assert check(repo) == []


def test_the_skill_drift_lists_stop_collecting_past_the_sample(temp_dir) -> None:
    """A catalog is repository content: many entries naming one directory
    would otherwise cross-multiply into an unbounded list, so past the cap
    the message says "and more" rather than a count it cannot stand by."""
    entries = [{"name": f"almanac-{n}", "source": "./plugins/almanac"} for n in range(6)]
    repo = marketplace(
        temp_dir,
        "capped-drift",
        {"plugins": entries},
        index({f"almanac-{n}": {"components": {"skills": []}} for n in range(6)}),
        skills=("tide-window",),
    )

    message = only(check(repo), "disagrees").message

    assert "skills only the plugin ships: " in message
    assert message.endswith(", and more")
    assert "and 2 more" not in message


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


@pytest.mark.parametrize("location", ["plugin-index.json"])
def test_an_index_away_from_its_catalog_is_reported(temp_dir, location) -> None:
    repo = marketplace(temp_dir, f"stray-{len(location)}", {"plugins": []}, None)
    stray = repo / location
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text(json.dumps(index({"almanac": {}})), encoding="utf-8")

    found = check(repo)

    assert len(found) == 1
    assert "must be in .grok-plugin/ or .claude-plugin/" in found[0].message
    assert found[0].file_path == stray


def test_a_stray_index_is_a_node_under_its_catalog(temp_dir) -> None:
    """Every file the rule reports on is in the tree: unsupported locations
    attach as index nodes marked ``stray``, so nothing is discovered by a
    filesystem probe from inside a rule."""
    repo = marketplace(temp_dir, "stray-node", {"plugins": []}, None)
    stray = repo / "plugin-index.json"
    stray.write_text(json.dumps(index({"almanac": {}})), encoding="utf-8")

    tree = RepositoryContext(repo).lint_tree
    nodes = tree.find(GrokMarketplaceIndexNode)

    assert [(node.path, node.stray) for node in nodes] == [(stray, True)]
    assert tree.find(GrokMarketplaceConfigNode)[0].find(GrokMarketplaceIndexNode) == nodes


def test_a_stray_index_is_never_compared(temp_dir) -> None:
    """It is not read, so it has nothing to drift from: the catalog beside it
    lists a plugin the stray index does not."""
    repo = marketplace(temp_dir, "stray-not-compared", {"plugins": [url_entry("almanac")]}, None)
    (repo / "plugin-index.json").write_text(json.dumps(index({})), encoding="utf-8")

    assert [m for m in messages(check(repo)) if "disagrees" in m] == []


# ── Index entries Grok cannot use ────────────────────────────────


def test_an_index_entry_that_is_not_an_object_is_reported(temp_dir) -> None:
    """The key is claimed, so no other branch would ever name it, and Grok
    displays nothing for it."""
    repo = marketplace(
        temp_dir,
        "scalar-entry",
        {"plugins": [url_entry("almanac", SHA_A)]},
        index({"almanac": "garbage"}),
    )

    assert "entries that are not objects: almanac" in only(check(repo), "disagrees").message


@pytest.mark.parametrize(
    "listed",
    [{}, {"components": {}}, {"components": {"skills": "tide-window"}}],
    ids=["no-components", "no-skills", "skills-not-a-list"],
)
def test_an_index_entry_listing_no_usable_skills_reports_what_ships(temp_dir, listed) -> None:
    """The index is the browser's only component source, so an entry with no
    usable ``skills`` displays none — an empty listing, not a comparison to
    skip."""
    repo = marketplace(
        temp_dir,
        f"empty-listing-{len(str(listed))}",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index({"almanac": listed}),
        skills=("tide-window",),
    )

    assert (
        "skills only the plugin ships: almanac/tide-window"
        in only(check(repo), "disagrees").message
    )


# ── Skill names, as the generator writes them ────────────────────


def test_a_skill_named_in_its_frontmatter_is_not_drift(temp_dir) -> None:
    """``plugin_catalog.py`` writes the SKILL.md frontmatter name and falls
    back to the directory, so an index carrying the declared name is exactly
    right — reading the directory alone reported the same skill twice, once
    as missing and once as extra."""
    repo = marketplace(
        temp_dir,
        "declared-name",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index({"almanac": {"components": {"skills": [{"name": "tide-window-v2"}]}}}),
        skills=(("tide-window", "tide-window-v2"),),
    )

    assert check(repo) == []


def test_a_skill_named_after_its_directory_is_not_drift(temp_dir) -> None:
    """The fallback half of the same rule: an index generated before the
    frontmatter name landed carries the directory name."""
    repo = marketplace(
        temp_dir,
        "directory-name",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index({"almanac": {"components": {"skills": [{"name": "tide-window"}]}}}),
        skills=(("tide-window", "tide-window-v2"),),
    )

    assert check(repo) == []


def test_a_declared_skills_path_that_is_itself_a_skill_is_read(temp_dir) -> None:
    """The generator treats a declared ``skills`` entry as one skill
    directory and unions it with ``skills/``; the runtime reads the children
    of the declared directory instead. A name either reader produces is not
    drift."""
    repo = marketplace(
        temp_dir,
        "declared-root",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index({"almanac": {"components": {"skills": [{"name": "bundled"}]}}}),
        manifest={"name": "almanac", "skills": "./bundled"},
    )
    bundled = repo / "plugins" / "almanac" / "bundled"
    bundled.mkdir(parents=True)
    (bundled / "SKILL.md").write_text(skill_doc("bundled"), encoding="utf-8")

    assert check(repo) == []


def test_a_skill_under_a_declared_directory_is_read(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "declared-children",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        index({"almanac": {"components": {"skills": [{"name": "ebb-window"}]}}}),
        manifest={"name": "almanac", "skills": "./bundled"},
    )
    nested = repo / "plugins" / "almanac" / "bundled" / "ebb-window"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(skill_doc("ebb-window"), encoding="utf-8")

    assert check(repo) == []


# ── Fixtures ─────────────────────────────────────────────────────


def test_the_broken_fixture_is_one_consolidated_finding(broken) -> None:
    found = check(broken)

    assert len(found) == 1
    message = found[0].message
    # The exact clause, so the bound on the sample and the deduplication
    # behind it are pinned rather than merely executed: the fixture drifts
    # six names, one of them the duplicated ``escaping`` — and ``moved``,
    # whose local path resolves nowhere, is not one of them.
    assert "not in the index: abbreviated, berth-notes, counted, and 3 more" in message
    assert "moved" not in message
    assert "not in the catalog: retired" in message
    assert "'sha' differs: drifted" in message
    assert "skills only the index lists: current-log/ebb-window" in message


def test_the_clean_fixture_reports_nothing(tmp_path) -> None:
    assert check(copy_fixture("grok/marketplace-clean", tmp_path)) == []


def test_a_non_finite_number_in_the_index_is_invalid_json(temp_dir) -> None:
    """Grok's parser refuses the document over a token in a field nothing
    reads, and an index it cannot parse is ignored without a word."""
    repo = marketplace(temp_dir, "nan-index", {"plugins": [url_entry("almanac", SHA_A)]}, index({}))
    (repo / ".grok-plugin" / "plugin-index.json").write_text(
        '{"version": 1, "plugins": {}, "generated": NaN}', encoding="utf-8"
    )

    found = check(repo)

    assert len(found) == 1
    assert found[0].message == "Invalid JSON: non-finite JSON number: NaN"


def test_a_sha_on_a_local_source_is_not_compared(temp_dir) -> None:
    """Grok pins only a url source. A ``sha`` on a local entry installs
    nothing, so an index without one is not behind."""
    repo = marketplace(
        temp_dir,
        "local-sha",
        {
            "plugins": [
                {
                    "name": "almanac",
                    "source": {"type": "local", "path": "./plugins/almanac", "sha": SHA_A},
                }
            ]
        },
        index({"almanac": {"components": {"skills": [{"name": "tide-window"}]}}}),
        skills=("tide-window",),
    )

    assert check(repo) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("./plugins/nowhere", id="local-missing"),
        pytest.param("../outside", id="local-escaping"),
        pytest.param({"source": "url", "sha": SHA_A}, id="url-without-url"),
    ],
)
def test_an_entry_grok_drops_is_not_also_index_drift(temp_dir, source) -> None:
    """``grok-marketplace-json-valid`` names an unloadable entry. Reporting
    it here too would say the index is behind on a plugin that installs
    nowhere."""
    repo = marketplace(
        temp_dir,
        f"unloadable-{len(str(source))}",
        {"plugins": [{"name": "almanac", "source": source}]},
        index({}),
    )

    assert check(repo) == []


def test_the_severity_override_reaches_the_primary_finding(temp_dir) -> None:
    repo = marketplace(
        temp_dir,
        "downgraded",
        {"plugins": [url_entry("almanac", SHA_A), url_entry("tides", SHA_B)]},
        index({"almanac": {"sha": SHA_A}}),
    )

    found = check(repo, {"severity": "info"})

    assert [v.severity for v in found] == [Severity.INFO]
    assert "not in the index: tides" in found[0].message
