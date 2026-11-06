"""Released OpenClaw theme declarations, including JSON5 artwork duplicates."""

import copy
import json
import shutil
from pathlib import Path

import pytest

from skillsaw.formats.openclaw_themes import theme_manifest_error
from tests.cli_runner import run_cli

FIXTURES = Path(__file__).parent / "fixtures" / "openclaw" / "themes"
RULE = "openclaw-manifest-valid"


def manifest():
    return json.loads((FIXTURES / "valid" / "openclaw.plugin.json").read_text())


def theme_error(tmp_path, **changes):
    data = manifest()
    data["themes"][0].update(changes)
    return theme_manifest_error(data, tmp_path / "unused.json")


@pytest.mark.parametrize(
    ("name", "fragment"),
    [
        ("valid", None),
        ("null", "'themes'"),
        ("object", "'themes'"),
        ("reserved-owner", "reserved user"),
        ("invalid-source", "source"),
        ("invalid-artwork", "built-in catalog"),
        ("invalid-timing", "crossMs"),
        ("duplicate-artwork", "duplicate artwork"),
    ],
)
def test_cli_theme_fixtures(tmp_path, name, fragment):
    repo = Path(shutil.copytree(FIXTURES / name, tmp_path / "repo"))
    result = run_cli(["lint", str(repo), "--rule", RULE, "--format", "json"])
    violations = json.loads(result.stdout)["violations"]
    assert result.returncode == (1 if fragment else 0)
    if fragment:
        assert len(violations) == 1
        assert violations[0]["rule_id"] == RULE
        assert fragment in violations[0]["message"]
        assert not violations[0].get("line")
    else:
        assert violations == []


def test_theme_checks_remain_opt_in_and_honor_severity(tmp_path):
    repo = Path(shutil.copytree(FIXTURES / "object", tmp_path / "repo"))
    result = run_cli(["lint", str(repo), "--format", "json", "--verbose"])
    assert all(v["rule_id"] != RULE for v in json.loads(result.stdout)["violations"])
    (repo / ".skillsaw.yaml").write_text(
        f"rules:\n  {RULE}:\n    enabled: true\n    severity: info\n"
    )
    result = run_cli(["lint", str(repo), "--format", "json", "--verbose"])
    found = [v for v in json.loads(result.stdout)["violations"] if v["rule_id"] == RULE]
    assert len(found) == 1
    assert found[0]["severity"].lower() == "info"


@pytest.mark.parametrize("themes", [None, {}, "night", [None], [False], ["night"]])
def test_invalid_theme_containers(tmp_path, themes):
    assert theme_manifest_error({"id": "pack", "themes": themes}, tmp_path / "unused.json")


def test_omitted_empty_and_theme_count_boundaries(tmp_path):
    path = tmp_path / "unused.json"
    assert theme_manifest_error({"id": "user"}, path) is None
    assert theme_manifest_error({"id": "user", "themes": []}, path) is None
    data = manifest()
    data["themes"] = [{**data["themes"][0], "id": f"theme-{i}"} for i in range(32)]
    assert theme_manifest_error(data, path) is None
    data["themes"].append({**data["themes"][0], "id": "extra"})
    assert "32" in theme_manifest_error(data, path)


@pytest.mark.parametrize("owner", ["@scope/Pack", "pack/one", "Pack.Name", "User", "a" * 254])
def test_portable_plugin_owners(tmp_path, owner):
    data = manifest()
    data["id"] = owner
    assert theme_manifest_error(data, tmp_path / "unused.json") is None


@pytest.mark.parametrize("owner", ["user", "user/pack", "a" * 255, "has space", "../pack", "a//b"])
def test_invalid_plugin_owners(tmp_path, owner):
    data = manifest()
    data["id"] = owner
    assert "plugin id" in theme_manifest_error(data, tmp_path / "unused.json")


@pytest.mark.parametrize("identifier", [None, 1, "", "Upper", "-start", "a/b", "a" * 65])
def test_invalid_local_ids(tmp_path, identifier):
    assert ".id'" in theme_error(tmp_path, id=identifier)


def test_duplicate_theme_ids_and_maximum_id(tmp_path):
    data = manifest()
    data["themes"][0]["id"] = "1" + "a" * 63
    assert theme_manifest_error(data, tmp_path / "unused.json") is None
    data["themes"].append(copy.deepcopy(data["themes"][0]))
    assert "unique" in theme_manifest_error(data, tmp_path / "unused.json")


@pytest.mark.parametrize("field,limit", [("name", 80), ("description", 320)])
def test_display_text_boundaries(tmp_path, field, limit):
    for value in (None, 12, "", " \t", "x\n", "x\x7f", "x" * (limit + 1), "😀" * (limit // 2 + 1)):
        assert field in theme_error(tmp_path, **{field: value})
    for value in ("x" * limit, " " + "x" * limit + " ", "😀" * (limit // 2), "\u0085"):
        assert theme_error(tmp_path, **{field: value}) is None


@pytest.mark.parametrize("field", ["id", "name", "description", "source"])
def test_required_theme_fields(tmp_path, field):
    data = manifest()
    del data["themes"][0][field]
    assert theme_manifest_error(data, tmp_path / "unused.json")


def test_unknown_theme_fields_and_unknown_manifest_metadata(tmp_path):
    assert "supports only" in theme_error(tmp_path, future=True)
    data = manifest()
    data["future"] = {"anything": [1, 2, 3]}
    assert theme_manifest_error(data, tmp_path / "unused.json") is None


@pytest.mark.parametrize(
    "source",
    [
        None,
        "",
        "../theme.json",
        "/theme.json",
        "a/../theme.json",
        "a//theme.json",
        "a\\theme.json",
        "https://example.com/theme.json",
        "C:/theme.json",
        "theme.js",
        "theme.json?x=1",
        "././theme.json",
    ],
)
def test_invalid_sources(tmp_path, source):
    assert "source" in theme_error(tmp_path, source=source)


@pytest.mark.parametrize("source", ["a.json", "./a.json", "themes/My-Theme.JSON", "a..b/c.json"])
def test_valid_source_paths_need_not_exist(tmp_path, source):
    assert theme_error(tmp_path, source=source) is None


@pytest.mark.parametrize(
    "kind,builtin", [("icons", "claw"), ("hats", "fedora"), ("critters", "fedora")]
)
def test_artwork_container_and_id_boundaries(tmp_path, kind, builtin):
    value = {"source": "critter.svg"} if kind == "critters" else "art.svg"
    for invalid in (None, [], "artwork"):
        assert kind in theme_error(tmp_path, **{kind: invalid})
    for key in ("", "Upper", "-start", "hat.svg", "x" * 33, builtin):
        assert kind in theme_error(tmp_path, **{kind: {key: value}})
    entries = {str(i) + "x" * 31: value for i in range(8)}
    assert theme_error(tmp_path, **{kind: entries}) is None
    entries["extra"] = value
    assert "8 entries" in theme_error(tmp_path, **{kind: entries})
    assert theme_error(tmp_path, **{kind: {}}) is None


@pytest.mark.parametrize(
    "kind,identifier",
    [
        ("icons", "claw"),
        ("icons", "mark"),
        ("hats", "crown"),
        ("hats", "santa"),
        ("hats", "party"),
        ("hats", "pumpkin"),
        ("critters", "penguin"),
    ],
)
def test_builtin_artwork_collisions(tmp_path, kind, identifier):
    value = {"source": "art.svg"} if kind == "critters" else "art.svg"
    assert "built-in" in theme_error(tmp_path, **{kind: {identifier: value}})


@pytest.mark.parametrize(
    "source", [None, "../a.svg", "/a.svg", "a//b.svg", "a\\b.svg", "a.png", "a.svg?x=1"]
)
def test_invalid_artwork_paths(tmp_path, source):
    assert "SVG" in theme_error(tmp_path, icons={"icon": source})
    assert "SVG" in theme_error(tmp_path, hats={"hat": source})
    assert "SVG" in theme_error(tmp_path, critters={"critter": {"source": source}})


@pytest.mark.parametrize(
    "value", [None, [], "critter.svg", {}, {"source": "critter.svg", "extra": True}]
)
def test_invalid_critter_shape(tmp_path, value):
    assert "critters" in theme_error(tmp_path, critters={"critter": value})


@pytest.mark.parametrize(
    "title", [None, 2, "x" * 61, "😀" * 31, "x\n", "x\x7f", "x\u202e", "\ud800"]
)
def test_invalid_critter_title(tmp_path, title):
    assert "titles" in theme_error(
        tmp_path, critters={"critter": {"source": "a.svg", "title": title}}
    )


@pytest.mark.parametrize("title", ["", "x" * 60, "😀" * 30])
def test_valid_critter_title(tmp_path, title):
    assert theme_error(tmp_path, critters={"critter": {"source": "a.svg", "title": title}}) is None


@pytest.mark.parametrize(
    "crossing", [True, None, "12000", 4999, 90001, 12000.5, float("nan"), float("inf")]
)
def test_invalid_critter_timing(tmp_path, crossing):
    assert "crossMs" in theme_error(
        tmp_path, critters={"critter": {"source": "a.svg", "crossMs": crossing}}
    )


@pytest.mark.parametrize("crossing", [5000, 90000, 12000.0])
def test_valid_critter_timing(tmp_path, crossing):
    assert (
        theme_error(tmp_path, critters={"critter": {"source": "a.svg", "crossMs": crossing}})
        is None
    )


@pytest.mark.parametrize("kind", ["icons", "hats", "critters"])
def test_duplicate_artwork_json_and_json5(tmp_path, kind):
    value = '{"source":"a.svg"}' if kind == "critters" else '"a.svg"'
    for index, artwork in enumerate(
        (
            f'"{kind}":{{"beret":{value},"b\\u0065ret":{value}}}',
            f"{kind}: {{beret: {value}, beret: {value}}}",
        )
    ):
        path = tmp_path / f"manifest-{index}.json"
        path.write_text(
            '{"id":"pack","themes":[{"id":"a","name":"A","description":"A theme","source":"a.json",'
            + artwork
            + "}]}"
        )
        from skillsaw.formats.openclaw import read_manifest

        data, error = read_manifest(path)
        assert error is None
        assert "duplicate artwork" in theme_manifest_error(data, path)


def test_unrelated_duplicate_keys_keep_last_value_semantics(tmp_path):
    from skillsaw.formats.openclaw import read_manifest

    path = tmp_path / "manifest.json"
    path.write_text('{"id":"old","id":"pack","configSchema":{"x":1,"x":2},"themes":[]}')
    data, error = read_manifest(path)
    assert error is None
    assert theme_manifest_error(data, path) is None
