"""``grok-marketplace-json-valid`` — the catalog, and the two failure scopes.

A catalog Grok cannot read is discarded whole and discovery falls back to
scanning ``plugins/``, which in a conventional layout hides the loss. An
entry defect drops one entry silently. Both were measured against Grok Build
1.0.13 by building catalogs in an isolated ``GROK_HOME`` and reading back
``grok plugin list --json --available``.

The negative cases matter as much as the positive ones: the loader keys a
local source on ``path`` alone, so five discriminator spellings install
identically and requiring one would be the rule's largest false-positive
risk.
"""

from __future__ import annotations

import json

import pytest

from skillsaw.context import RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokMarketplaceJsonValidRule

from tests.grok._helpers import (
    at,
    copy_fixture,
    messages,
    only,
    run_rule,
    write_catalog,
    write_plugin,
    write_repo,
)

# Commit ids assembled from halves so no 40-character hex literal sits
# contiguously in a source file.
SHA_A = "1f9d0c73a86b24e510" + "7cad3f88b90250e6c147da"
SHA_B = "70e4d2c81f6a35b09c" + "7e18d4a6f30b25ce817d94"
SHA_256 = SHA_A + SHA_B[:24]


def url_entry(name: str, **source) -> dict:
    return {
        "name": name,
        "description": f"The {name} plugin, cloned from a repository.",
        "source": {"source": "url", "url": f"https://example.invalid/{name}.git", **source},
    }


def catalog_repo(temp_dir, name: str, catalog, plugins=()):
    """A marketplace repository holding *catalog* and the *plugins* it lists."""
    repo = write_repo(temp_dir / name)
    write_catalog(repo, {"name": "harbour-plugins", **catalog})
    for relative_path, manifest in plugins:
        write_plugin(repo / relative_path, manifest)
    return repo


def check(repo, config=None, repo_types=None):
    return run_rule(GrokMarketplaceJsonValidRule, repo, config, repo_types)


@pytest.fixture
def broken(tmp_path):
    return copy_fixture("grok/marketplace-broken", tmp_path)


# ── Whole-catalog scope ──────────────────────────────────────────


def test_malformed_json_is_an_error(temp_dir) -> None:
    repo = write_repo(temp_dir / "bad-json")
    write_catalog(repo, {"plugins": []})
    (repo / ".grok-plugin" / "marketplace.json").write_text('{"plugins": [,]}', encoding="utf-8")

    assert any("Invalid JSON" in message for message in at(check(repo), Severity.ERROR))


@pytest.mark.parametrize(
    "catalog,expected",
    [
        pytest.param([], "Marketplace catalog must be a JSON object", id="top-level-array"),
        pytest.param({"plugins": []}, "Marketplace catalog missing required 'name'", id="no-name"),
        pytest.param(
            {"name": "x", "plugins": {}}, "'plugins' must be an array", id="plugins-object"
        ),
    ],
)
def test_a_catalog_grok_discards_is_an_error(temp_dir, catalog, expected) -> None:
    repo = write_repo(temp_dir / f"discarded-{expected[:8]}")
    marker = repo / ".grok-plugin"
    marker.mkdir(parents=True)
    (marker / "marketplace.json").write_text(json.dumps(catalog), encoding="utf-8")

    assert at(check(repo), Severity.ERROR) == [expected]


def test_a_forced_type_with_no_catalog_reports_the_missing_file(temp_dir) -> None:
    repo = write_repo(temp_dir / "forced")

    found = check(repo, repo_types={RepositoryType.GROK_MARKETPLACE})

    assert at(found, Severity.ERROR) == ["Marketplace file not found"]


# ── Entry scope ──────────────────────────────────────────────────


def test_an_entry_that_is_not_an_object_is_an_error(temp_dir) -> None:
    repo = catalog_repo(temp_dir, "string-entry", {"plugins": ["./plugins/almanac"]})

    assert at(check(repo), Severity.ERROR) == ["plugins[0] must be an object"]


@pytest.mark.parametrize(
    "entry,expected",
    [
        pytest.param({"source": "./plugins/almanac"}, "missing required 'name'", id="absent"),
        pytest.param(
            {"name": 7, "source": "./plugins/almanac"}, "'name' must be a string", id="non-string"
        ),
    ],
)
def test_an_entry_with_no_usable_name_is_an_error(temp_dir, entry, expected) -> None:
    repo = catalog_repo(
        temp_dir,
        f"name-{expected[:8]}",
        {"plugins": [entry]},
        plugins=[(("plugins/almanac"), {"name": "almanac"})],
    )

    assert any(expected in message for message in at(check(repo), Severity.ERROR))


def test_a_missing_source_is_an_error(temp_dir) -> None:
    repo = catalog_repo(temp_dir, "no-source", {"plugins": [{"name": "almanac"}]})

    assert at(check(repo), Severity.ERROR) == ["plugins[0] missing required 'source'"]


def test_duplicates_are_counted_on_the_resolved_manifest_name(temp_dir) -> None:
    """An entry named ``Bad Name!`` pointing at ``plugins/almanac`` surfaces
    as ``almanac`` and collides with an entry named ``almanac``."""
    repo = catalog_repo(
        temp_dir,
        "resolved-duplicate",
        {
            "plugins": [
                {"name": "Bad Name!", "source": {"type": "local", "path": "./plugins/almanac"}},
                {"name": "almanac", "source": "./plugins/almanac"},
            ]
        },
        plugins=[("plugins/almanac", {"name": "almanac"})],
    )

    found = only(check(repo), "Duplicate")

    assert found.severity == Severity.ERROR
    assert "'almanac' at plugins[0], plugins[1]" in found.message


def test_rejected_catalog_skips_entry_installation_advice(broken) -> None:
    assert at(check(broken), Severity.ERROR) == [
        "plugins[7].source.sha must be a string or null",
        "plugins[10] missing required 'name'",
    ]


def test_one_duplicated_name_is_one_finding(temp_dir) -> None:
    repo = catalog_repo(temp_dir, "repeated", {"plugins": [url_entry("almanac", sha=SHA_A)] * 3})
    assert messages(check(repo)) == [
        "Duplicate plugin name 'almanac' at plugins[0], plugins[1], plugins[2]"
    ]


def test_two_catalogs_in_one_repository_do_not_collide(temp_dir) -> None:
    """Each package is its own marketplace; the measured install failure is
    two entries inside one catalog."""
    repo = write_repo(temp_dir / "two-marketplaces")
    for package in ("harbour", "estuary"):
        write_catalog(
            repo / "packages" / package,
            {"name": package, "plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
        )
        write_plugin(repo / "packages" / package / "plugins" / "almanac", {"name": "almanac"})

    assert [m for m in messages(check(repo)) if "Duplicate" in m] == []


@pytest.mark.parametrize(
    "path,expected",
    [
        pytest.param(
            "./plugins/nope", "is not a directory under the marketplace root", id="missing"
        ),
        pytest.param(
            "../outside", "contains '..'; paths must stay inside the marketplace root", id="dotdot"
        ),
        pytest.param(
            "/etc", "is absolute; paths must stay inside the marketplace root", id="absolute"
        ),
    ],
)
def test_a_local_source_that_does_not_resolve_is_an_error(temp_dir, path, expected) -> None:
    repo = catalog_repo(
        temp_dir, f"local-{expected[:6]}", {"plugins": [{"name": "almanac", "source": path}]}
    )

    assert any(expected in message for message in at(check(repo), Severity.ERROR))


def test_a_source_whose_plugin_marker_escapes_is_an_error(temp_dir) -> None:
    """Discovery drops a directory whose ``.grok-plugin`` resolves elsewhere,
    so no plugin node is built and none of the plugin checks run — the entry
    would otherwise be silently lost."""
    repo = catalog_repo(
        temp_dir,
        "escaping-marker-source",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}]},
    )
    write_plugin(repo / "plugins" / "tide-charts", {"name": "tide-charts"})
    (repo / "plugins" / "almanac").mkdir(parents=True)
    (repo / "plugins" / "almanac" / ".grok-plugin").symlink_to(
        repo / "plugins" / "tide-charts" / ".grok-plugin"
    )

    assert at(check(repo), Severity.ERROR) == [
        "plugins[0].source: './plugins/almanac' has a '.grok-plugin' that resolves outside it"
    ]


def test_an_entry_grok_drops_is_not_counted_as_a_duplicate(temp_dir) -> None:
    """A dropped entry installs nothing, so it collides with nothing: one
    finding for the defect, and no duplicate beside it."""
    repo = catalog_repo(
        temp_dir,
        "dropped-not-duplicated",
        {"plugins": [{"name": "almanac", "source": "./plugins/almanac"}, {"name": "almanac"}]},
        plugins=[("plugins/almanac", {"name": "almanac"})],
    )

    assert at(check(repo), Severity.ERROR) == ["plugins[1] missing required 'source'"]


def test_an_empty_source_string_is_an_error(temp_dir) -> None:
    repo = catalog_repo(temp_dir, "empty-source", {"plugins": [{"name": "a", "source": ""}]})

    assert at(check(repo), Severity.ERROR) == ["plugins[0].source is an empty path"]


def test_a_source_naming_neither_a_path_nor_a_url_warns(temp_dir) -> None:
    """A warning rather than an error: the loader keys on the fields, so a
    source shape added upstream must not break a catalog that works."""
    repo = catalog_repo(
        temp_dir, "shapeless", {"plugins": [{"name": "a", "source": {"type": "local"}}]}
    )

    assert at(check(repo), Severity.WARNING) == [
        "plugins[0].source names neither a local 'path' nor a 'url'"
    ]


# ── The url source's pin ─────────────────────────────────────────


@pytest.mark.parametrize(
    "source,expected",
    [
        pytest.param({}, "source has no 'sha'", id="absent"),
        pytest.param({"sha": 12345}, "must be a string", id="non-string"),
        pytest.param({"sha": "4b7c1e9"}, "is not a 40 or 64 character", id="abbreviated"),
        pytest.param({"sha": "main"}, "is not a 40 or 64 character", id="branch"),
    ],
)
def test_an_unpinned_url_source_is_an_error(temp_dir, source, expected) -> None:
    repo = catalog_repo(
        temp_dir, f"pin-{expected[:8]}", {"plugins": [url_entry("almanac", **source)]}
    )

    assert any(expected in message for message in at(check(repo), Severity.ERROR))


def test_a_40_hex_sha_reports_nothing(temp_dir) -> None:
    repo = catalog_repo(temp_dir, "pinned-40", {"plugins": [url_entry("almanac", sha=SHA_A)]})

    assert check(repo) == []


@pytest.mark.parametrize("sha", [SHA_256, SHA_A.upper()], ids=["64-hex", "uppercase"])
def test_a_sha_the_upstream_validator_refuses_is_one_info(temp_dir, sha) -> None:
    """The installer takes 40 or 64 hex, case-insensitively — an uppercase
    value passed straight through to fetch-by-sha — while
    ``validate-catalog.py`` requires 40 lowercase."""
    repo = catalog_repo(
        temp_dir, f"pinned-{len(sha)}", {"plugins": [url_entry("almanac", sha=sha)]}
    )

    found = at(check(repo), Severity.INFO)

    assert len(found) == 1
    assert "is not 40 lowercase hex characters" in found[0]
    assert at(check(repo), Severity.ERROR) == []


def test_require_sha_off_drops_only_the_absent_case(temp_dir) -> None:
    repo = catalog_repo(
        temp_dir,
        "moving-branch",
        {"plugins": [url_entry("almanac"), url_entry("tides", sha="4b7c1e9")]},
    )

    found = messages(check(repo, {"require-sha": False}))

    assert not any("has no 'sha'" in message for message in found)
    assert any("is not a 40 or 64 character" in message for message in found)


@pytest.mark.parametrize("path", ["/plugins/almanac", "../almanac"])
def test_a_url_source_subdirectory_that_is_not_relative_warns(temp_dir, path) -> None:
    repo = catalog_repo(
        temp_dir, f"subdir-{len(path)}", {"plugins": [url_entry("almanac", sha=SHA_A, path=path)]}
    )

    found = at(check(repo), Severity.WARNING)

    assert len(found) == 1
    assert "relative subdirectory of the cloned repository" in found[0]


@pytest.mark.parametrize("path", ["plugins/almanac", "plugins\\almanac"])
def test_a_url_source_subdirectory_reports_nothing(temp_dir, path) -> None:
    repo = catalog_repo(
        temp_dir,
        "subdir-ok",
        {"plugins": [url_entry("almanac", sha=SHA_A, path=path)]},
    )

    assert check(repo) == []


# ── Never reported ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "source",
    [
        pytest.param({"type": "local", "path": "./plugins/almanac"}, id="type-local"),
        pytest.param({"source": "local", "path": "./plugins/almanac"}, id="source-local"),
        pytest.param("./plugins/almanac", id="bare-string"),
        pytest.param({"path": "./plugins/almanac"}, id="no-discriminator"),
        pytest.param({"type": "totally-bogus", "path": "./plugins/almanac"}, id="bogus-type"),
    ],
)
def test_every_local_spelling_grok_installs_reports_nothing(temp_dir, source) -> None:
    """Measured: all five installed identically, because the loader keys on
    ``path`` alone. Requiring a discriminator would be a false positive."""
    repo = catalog_repo(
        temp_dir,
        f"spelling-{str(source)[:12].replace('/', '-')}",
        {"plugins": [{"name": "almanac", "source": source}]},
        plugins=[("plugins/almanac", {"name": "almanac"})],
    )

    assert check(repo) == []


def test_an_omitted_plugin_vector_is_a_valid_empty_catalog(temp_dir) -> None:
    repo = catalog_repo(temp_dir, "empty-catalog", {"name": "harbour-plugins"})
    assert check(repo) == []


@pytest.mark.parametrize("name", ["Bad Name!", ""])
def test_an_entry_name_grok_overrides_reports_nothing(temp_dir, name) -> None:
    """The catalog name is replaced by the plugin's manifest name, so its
    format is not this rule's to enforce."""
    repo = catalog_repo(
        temp_dir,
        "loud-entry-name",
        {"plugins": [{"name": name, "source": "./plugins/almanac"}]},
        plugins=[("plugins/almanac", {"name": "almanac"})],
    )

    assert check(repo) == []


def test_unknown_keys_report_nothing(temp_dir) -> None:
    repo = catalog_repo(
        temp_dir,
        "unknown-keys",
        {
            "colour": "blue",
            "plugins": [{**url_entry("almanac", sha=SHA_A), "category": "productivity", "rank": 1}],
        },
    )

    assert check(repo) == []


def test_the_clean_fixture_reports_nothing(tmp_path) -> None:
    assert check(copy_fixture("grok/marketplace-clean", tmp_path)) == []


@pytest.mark.parametrize(
    "source", [7, ["./plugins/almanac"], True], ids=["number", "array", "bool"]
)
def test_a_source_that_is_neither_a_string_nor_an_object_is_an_error(temp_dir, source) -> None:
    """Not the softer "names neither a local 'path' nor a 'url'" warning: a
    source of this shape is not a source at all."""
    repo = catalog_repo(
        temp_dir,
        f"source-{type(source).__name__}",
        {"plugins": [{"name": "almanac", "description": "Almanac.", "source": source}]},
    )

    assert at(check(repo), Severity.ERROR) == [
        "plugins[0].source must be a path string or an object"
    ]


@pytest.mark.parametrize(
    "source,severity,message",
    [
        (
            {"source": "url", "sha": SHA_A},
            Severity.WARNING,
            "names neither a local 'path' nor a 'url'",
        ),
        (
            {"url": None, "sha": SHA_A},
            Severity.WARNING,
            "names neither a local 'path' nor a 'url'",
        ),
        (
            {"source": "url", "url": "", "sha": SHA_A},
            Severity.ERROR,
            "is a url source with no 'url' to clone",
        ),
    ],
    ids=["absent", "null", "empty"],
)
def test_a_source_with_no_location_reports_its_effective_kind(
    temp_dir, source, severity, message
) -> None:
    """Only the non-null URL is remote; the other two lack a local path."""
    repo = catalog_repo(
        temp_dir,
        f"no-url-{len(str(source))}",
        {"plugins": [{"name": "almanac", "description": "Almanac.", "source": source}]},
    )

    found = check(repo)
    assert [(v.severity, v.message) for v in found] == [(severity, f"plugins[0].source {message}")]


def test_a_non_finite_number_is_invalid_json(temp_dir) -> None:
    """Grok's parser refuses the whole document — measured, ``grok plugin
    validate`` on a manifest holding one reports "failed to parse"."""
    repo = write_repo(temp_dir / "nan-catalog")
    write_catalog(repo, {"plugins": []})
    (repo / ".grok-plugin" / "marketplace.json").write_text(
        '{"plugins": [], "extra": NaN}', encoding="utf-8"
    )

    assert at(check(repo), Severity.ERROR) == ["Invalid JSON: non-finite JSON number: NaN"]


def test_a_sha_with_a_trailing_newline_is_an_error(temp_dir) -> None:
    """``$`` matches before a final newline and ``\\A``/``\\Z`` do not; the
    installer refuses the value either way."""
    repo = catalog_repo(
        temp_dir, "trailing-newline", {"plugins": [url_entry("almanac", sha=SHA_A + "\n")]}
    )

    assert any(
        "is not a 40 or 64 character" in message for message in at(check(repo), Severity.ERROR)
    )


def test_a_local_source_symlinked_out_of_the_marketplace_is_an_error(temp_dir) -> None:
    """The symlink arm of the escape check, at rule level: no ``..`` and not
    absolute, and still outside the package."""
    outside = temp_dir / "outside"
    (outside / "sediment").mkdir(parents=True)
    repo = catalog_repo(
        temp_dir,
        "symlinked-source",
        {"plugins": [{"name": "sediment", "source": "./plugins/sediment"}]},
    )
    (repo / "plugins").mkdir(exist_ok=True)
    (repo / "plugins" / "sediment").symlink_to(outside / "sediment")

    found = at(check(repo), Severity.ERROR)

    assert found == [
        "plugins[0].source: './plugins/sediment' resolves outside the marketplace root "
        "— check for a symlink"
    ]


def test_the_severity_override_reaches_the_primary_finding(temp_dir) -> None:
    """No finding hardcodes the rule's own severity, so a project that wants
    the catalog errors as warnings gets them."""
    repo = catalog_repo(
        temp_dir,
        "downgraded",
        {"plugins": [{"source": "./plugins/almanac"}]},
        plugins=(("plugins/almanac", {"name": "almanac"}),),
    )

    found = check(repo, {"severity": "warning"})

    assert at(found, Severity.ERROR) == []
    assert at(found, Severity.WARNING) == ["plugins[0] missing required 'name'"]
