"""``grok-plugin-json-valid`` — the manifest, and what each defect costs.

Severity is the whole point of the rule, so the tests assert it rather than
counting findings: a manifest Grok refuses costs the entire plugin
directory, a declared path that escapes or is missing costs that component
list, and metadata costs nothing but the browser's listing. The scopes come
from a matrix run against Grok Build 1.0.13; ``skillsaw.formats.grok``
records it.
"""

from __future__ import annotations

import json

import pytest

from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokPluginJsonValidRule

from tests.grok._helpers import (
    at,
    copy_fixture,
    messages,
    only,
    run_rule,
    write_plugin,
    write_repo,
)

MANIFEST = {
    "name": "tide-charts",
    "version": "1.0.0",
    "description": "Shoreline survey windows from NOAA tide predictions.",
}

SKILL = (
    "---\nname: tide-window\ndescription: Find the low-tide windows long enough for a "
    "shoreline survey. Use when planning field work.\n---\n\n# Window\n\nAsk for the "
    "station id, then report each window.\n"
)


def plugin_repo(temp_dir, name: str, manifest):
    """A repository whose one plugin declares *manifest* and nothing else."""
    repo = write_repo(temp_dir / name)
    write_plugin(repo / "plugins" / "tide-charts", manifest)
    return repo


def check(repo, config=None):
    return run_rule(GrokPluginJsonValidRule, repo, config)


@pytest.fixture
def broken(tmp_path):
    return copy_fixture("grok/plugin-broken", tmp_path)


# ── The manifest Grok refuses: the whole directory ───────────────


def test_malformed_json_is_an_error(broken) -> None:
    assert any("Invalid JSON" in message for message in at(check(broken), Severity.ERROR))


def test_a_missing_name_is_an_error(broken) -> None:
    assert "Missing required field 'name'" in at(check(broken), Severity.ERROR)


def test_an_invalid_name_quotes_groks_own_rule(broken) -> None:
    found = only(check(broken), "Bad_Name")
    assert found.severity == Severity.ERROR
    assert "1-64 chars, lowercase alphanumeric and hyphens" in found.message


@pytest.mark.parametrize(
    "name,expected",
    [
        pytest.param("-lead", "must be 1-64", id="leading-hyphen"),
        pytest.param("trail-", "must be 1-64", id="trailing-hyphen"),
        pytest.param("UPPER", "must be 1-64", id="uppercase"),
        pytest.param("dot.name", "must be 1-64", id="dot"),
        pytest.param("a" * 65, "must be 1-64", id="too-long"),
        pytest.param("", "empty string", id="empty"),
    ],
)
def test_names_grok_rejects_are_errors(temp_dir, name, expected) -> None:
    repo = plugin_repo(
        temp_dir, f"name-{len(name)}-{name[:4] or 'blank'}", {**MANIFEST, "name": name}
    )

    found = at(check(repo), Severity.ERROR)

    assert any(expected in message for message in found), found


@pytest.mark.parametrize("name", ["123", "a", "a--b", "a" * 64])
def test_names_grok_accepts_report_nothing(temp_dir, name) -> None:
    repo = plugin_repo(temp_dir, f"ok-{len(name)}-{name[:4]}", {**MANIFEST, "name": name})

    assert check(repo) == []


def test_a_non_string_name_is_an_error(temp_dir) -> None:
    repo = plugin_repo(temp_dir, "numeric-name", {**MANIFEST, "name": 42})

    assert any("'name' must be a string" in m for m in at(check(repo), Severity.ERROR))


def test_a_manifest_that_is_not_an_object_is_an_error(temp_dir) -> None:
    repo = write_repo(temp_dir / "array-manifest")
    plugin = write_plugin(repo / "plugins" / "tide-charts", None)
    (plugin / ".grok-plugin" / "plugin.json").write_text('["tide-charts"]', encoding="utf-8")

    assert at(check(repo), Severity.ERROR) == ["Plugin manifest must be a JSON object"]


def test_no_manifest_is_not_a_finding(temp_dir) -> None:
    """A manifest is optional to Grok. What a manifest-less directory costs
    is grok-plugin-structure's to report, not this rule's."""
    repo = write_repo(temp_dir / "manifest-less")
    write_plugin(repo / "plugins" / "tide-charts", None)

    assert check(repo) == []


def test_the_severity_override_reaches_the_primary_finding(broken) -> None:
    """No finding hardcodes the rule's own severity, so a project that wants
    the manifest errors as warnings gets them."""
    found = only(check(broken, {"severity": "warning"}), "Bad_Name")

    assert found.severity == Severity.WARNING


# ── Declared paths: that component list ──────────────────────────


def test_an_escaping_path_warns(broken) -> None:
    found = only(check(broken), "'../../etc'")

    assert found.severity == Severity.WARNING
    assert "paths must stay inside the plugin root" in found.message


@pytest.mark.parametrize(
    "declared,fragment",
    [
        pytest.param("/etc/skills", "is absolute", id="absolute"),
        pytest.param("../../outside", "contains '..'", id="traversal"),
    ],
)
def test_every_escape_shape_warns(temp_dir, declared, fragment) -> None:
    repo = plugin_repo(temp_dir, f"escape-{fragment[:8]}", {**MANIFEST, "skills": [declared]})

    found = only(check(repo), "'skills'")

    assert found.severity == Severity.WARNING
    assert fragment in found.message


def test_a_symlinked_escape_warns(temp_dir) -> None:
    """Neither lexical check catches this one: the path has no '..' and is
    not absolute, and still lands outside the plugin."""
    repo = write_repo(temp_dir / "symlinked")
    outside = repo / "outside-skills"
    (outside / "tide-window").mkdir(parents=True)
    (outside / "tide-window" / "SKILL.md").write_text(SKILL, encoding="utf-8")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, "skills": ["linked"]})
    (plugin / "linked").symlink_to(outside)

    found = only(check(repo), "'skills'")

    assert found.severity == Severity.WARNING
    assert "resolves outside the plugin root — check for a symlink" in found.message


def test_a_path_that_is_not_in_the_plugin_warns(broken) -> None:
    found = only(check(broken), "'./bundled-skills'")

    assert found.severity == Severity.WARNING
    assert "is not in the plugin" in found.message


def test_a_hooks_string_naming_no_file_is_a_missing_path_not_a_type_error(broken) -> None:
    """``hooks`` is a path *or* the object itself, so a string that names
    nothing is a dropped file, never a wrong type."""
    found = only(check(broken), "'hooks'")

    assert found.severity == Severity.WARNING
    assert "is not in the plugin" in found.message
    assert "type" not in found.message


def test_check_paths_exist_off_keeps_the_escape_finding(broken) -> None:
    found = messages(check(broken, {"check-paths-exist": False}))

    assert not any("is not in the plugin" in message for message in found)
    assert any("must stay inside the plugin root" in message for message in found)


def test_an_inline_hooks_object_is_not_a_path(temp_dir) -> None:
    inline = {"Stop": [{"hooks": [{"type": "command", "command": "make lint"}]}]}
    repo = plugin_repo(temp_dir, "inline-hooks", {**MANIFEST, "hooks": inline})

    assert check(repo) == []


def test_an_empty_declared_path_warns(temp_dir) -> None:
    repo = plugin_repo(temp_dir, "empty-path", {**MANIFEST, "skills": [""]})

    assert at(check(repo), Severity.WARNING) == ["'skills' declares an empty path"]


# ── The override that replaces rather than extends ───────────────


def test_an_override_beside_a_populated_conventional_directory_warns(broken) -> None:
    found = only(check(broken), "replaces")

    assert found.severity == Severity.WARNING
    assert found.message == (
        "'skills' replaces 'skills/'; Grok loads nothing under it, including 'chart-margins'"
    )


def test_naming_the_conventional_directory_alongside_the_override_is_clean(temp_dir) -> None:
    repo = write_repo(temp_dir / "both-directories")
    plugin = write_plugin(
        repo / "plugins" / "tide-charts", {**MANIFEST, "skills": ["./extra-skills", "./skills"]}
    )
    for directory in ("skills/tide-window", "extra-skills/tide-legend"):
        (plugin / directory).mkdir(parents=True, exist_ok=True)
        (plugin / directory / "SKILL.md").write_text(SKILL, encoding="utf-8")

    assert [m for m in messages(check(repo)) if "replaces" in m] == []


def test_an_override_with_no_conventional_directory_is_clean(temp_dir) -> None:
    repo = write_repo(temp_dir / "no-conventional")
    plugin = write_plugin(
        repo / "plugins" / "tide-charts", {**MANIFEST, "skills": ["./extra-skills"]}
    )
    (plugin / "extra-skills" / "tide-window").mkdir(parents=True)
    (plugin / "extra-skills" / "tide-window" / "SKILL.md").write_text(SKILL, encoding="utf-8")

    assert check(repo) == []


def test_an_empty_conventional_directory_is_clean(temp_dir) -> None:
    """Nothing is lost when the directory the override displaces is empty."""
    repo = write_repo(temp_dir / "empty-conventional")
    plugin = write_plugin(
        repo / "plugins" / "tide-charts", {**MANIFEST, "skills": ["./extra-skills"]}
    )
    (plugin / "skills").mkdir()
    (plugin / "extra-skills" / "tide-window").mkdir(parents=True)
    (plugin / "extra-skills" / "tide-window" / "SKILL.md").write_text(SKILL, encoding="utf-8")

    assert check(repo) == []


# ── Metadata: nothing stops a load ───────────────────────────────


def test_a_non_semver_version_is_info(temp_dir) -> None:
    repo = plugin_repo(temp_dir, "date-version", {**MANIFEST, "version": "2026-04-11"})

    assert at(check(repo), Severity.INFO) == ["'version' '2026-04-11' is not a semantic version"]


def test_a_missing_description_is_info(temp_dir) -> None:
    repo = plugin_repo(temp_dir, "no-description", {"name": "tide-charts", "version": "1.0.0"})

    assert at(check(repo), Severity.INFO) == ["Missing 'description'"]


# ── Never reported ───────────────────────────────────────────────


def test_a_name_that_disagrees_with_the_directory_reports_nothing(temp_dir) -> None:
    """The manifest name wins everywhere — install, ``plugin list``,
    ``inspect`` and skill attribution — so demanding they match would report
    a plugin that works."""
    repo = write_repo(temp_dir / "renamed")
    write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, "name": "totally-different"})

    assert check(repo) == []


def test_unknown_keys_report_nothing(temp_dir) -> None:
    repo = plugin_repo(temp_dir, "unknown-keys", {**MANIFEST, "colour": "blue", "rank": 3})

    assert check(repo) == []


def test_a_bare_string_path_reports_nothing(temp_dir) -> None:
    """``skills`` is an untagged path-or-paths; a string is as valid as an
    array and Grok loads both."""
    repo = write_repo(temp_dir / "bare-string")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, "skills": "bundled"})
    (plugin / "bundled" / "tide-window").mkdir(parents=True)
    (plugin / "bundled" / "tide-window" / "SKILL.md").write_text(SKILL, encoding="utf-8")

    assert check(repo) == []


def test_the_clean_fixture_reports_nothing(tmp_path) -> None:
    assert check(copy_fixture("grok/plugin-clean", tmp_path)) == []
    assert check(copy_fixture("grok/plugin-declarations", tmp_path)) == []


def test_a_dual_manifest_plugin_reports_nothing(tmp_path) -> None:
    """The node addresses whichever manifest Grok resolves. A directory
    carrying both hosts' manifests keeps both hosts' results."""
    assert check(copy_fixture("grok/dual-manifest", tmp_path)) == []


def test_an_oversized_integer_is_invalid_json_not_a_crash(temp_dir) -> None:
    """On 3.11+ an integer past the digit limit raises bare ValueError
    rather than JSONDecodeError, and discovery reads this file too."""
    repo = write_repo(temp_dir / "huge-integer")
    plugin = write_plugin(repo / "plugins" / "tide-charts", None)
    (plugin / ".grok-plugin" / "plugin.json").write_text(
        json.dumps(MANIFEST)[:-1] + ',"depth":' + "1" * 5000 + "}", encoding="utf-8"
    )

    assert any("Invalid JSON" in message for message in at(check(repo), Severity.ERROR))


# ── Field shapes and path kinds ──────────────────────────────────


def test_a_non_finite_number_is_invalid_json(temp_dir) -> None:
    """Grok refuses the whole document — ``grok plugin validate`` on this
    manifest reported "failed to parse … expected value" and exit 1, which
    costs the whole plugin directory."""
    repo = write_repo(temp_dir / "nan-manifest")
    plugin = write_plugin(repo / "plugins" / "tide-charts", None)
    (plugin / ".grok-plugin" / "plugin.json").write_text(
        '{"name": "tide-charts", "limit": NaN}', encoding="utf-8"
    )

    assert at(check(repo), Severity.ERROR) == ["Invalid JSON: non-finite JSON number: NaN"]


def test_a_name_with_a_trailing_newline_is_an_error(temp_dir) -> None:
    """``$`` matches before a final newline and ``\\A``/``\\Z`` do not; the
    loader refuses the value either way."""
    repo = plugin_repo(temp_dir, "trailing-newline", {**MANIFEST, "name": "tide-charts\n"})

    assert any("must be 1-64" in message for message in at(check(repo), Severity.ERROR))


@pytest.mark.parametrize(
    "field,value,expected",
    [
        pytest.param(
            "skills", "README.md", "'skills': 'README.md' is not a directory", id="skills"
        ),
        pytest.param(
            "commands", "README.md", "'commands': 'README.md' is not a directory", id="commands"
        ),
        pytest.param("hooks", "hooks", "'hooks': 'hooks' is not a file", id="hooks"),
        pytest.param("mcpServers", "hooks", "'mcpServers': 'hooks' is not a file", id="mcpServers"),
    ],
)
def test_a_declared_path_of_the_wrong_kind_warns(temp_dir, field, value, expected) -> None:
    """Discovery reads the three component fields as directories and the two
    file fields as files, so the wrong kind costs what a missing path costs."""
    repo = write_repo(temp_dir / f"kind-{field}")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, field: value})
    (plugin / "README.md").write_text("# Tide charts\n", encoding="utf-8")
    (plugin / "hooks").mkdir()

    assert at(check(repo), Severity.WARNING) == [expected]


@pytest.mark.parametrize("field", ["hooks", "mcpServers"])
def test_an_array_valued_hooks_or_mcp_field_warns(temp_dir, field) -> None:
    """Measured: ``"hooks": ["hooks/hooks.json"]`` loaded as an empty inline
    document with no target while the same path as a bare string loaded as a
    file, and ``"mcpServers": ["servers.json"]`` loaded no servers at all."""
    repo = write_repo(temp_dir / f"array-{field}")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, field: ["config.json"]})
    (plugin / "config.json").write_text('{"hooks": {}}', encoding="utf-8")

    assert at(check(repo), Severity.WARNING) == [
        f"'{field}' is an array; Grok reads one path or one inline object"
    ]


@pytest.mark.parametrize("field", ["commands", "agents"])
def test_a_commands_or_agents_override_warns_like_skills(temp_dir, field) -> None:
    """All three override fields replace their conventional directory."""
    repo = write_repo(temp_dir / f"override-{field}")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, field: f"desk-{field}"})
    for directory in (field, f"desk-{field}"):
        (plugin / directory).mkdir()
        (plugin / directory / "note.md").write_text("---\ndescription: A note\n---\n\n# Note\n")

    assert at(check(repo), Severity.WARNING) == [
        f"'{field}' replaces '{field}/'; Grok loads nothing under it, including 'note.md'"
    ]


@pytest.mark.parametrize("field", ["hooks", "mcpServers"])
def test_the_inline_fields_never_warn_about_an_override(temp_dir, field) -> None:
    """``hooks`` and ``mcpServers`` name one file rather than a directory of
    components, so there is nothing for a declaration to displace — and both
    conventional files are present here."""
    repo = write_repo(temp_dir / f"no-override-{field}")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, field: "config.json"})
    (plugin / "config.json").write_text('{"hooks": {}}', encoding="utf-8")
    (plugin / "hooks").mkdir()
    (plugin / "hooks" / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
    (plugin / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")

    assert [m for m in messages(check(repo)) if "replaces" in m] == []


# ── Which manifest a finding is filed against ────────────────────


def test_each_finding_names_the_manifest_that_carries_it(broken) -> None:
    """Six plugin directories, and a finding attributed to the neighbouring
    one — or to the plugin directory instead of its manifest — would leave
    every message assertion above green."""
    plugins = broken / "plugins"

    filed = {(v.file_path, v.message.split(":")[0].split(" '")[0]) for v in check(broken)}

    assert (plugins / "Bad_Name" / ".grok-plugin" / "plugin.json", "Plugin name") in filed
    assert (
        plugins / "nameless" / ".grok-plugin" / "plugin.json",
        "Missing required field",
    ) in filed
    assert (plugins / "malformed" / ".grok-plugin" / "plugin.json", "Invalid JSON") in filed
    assert {v.file_path.name for v in check(broken)} == {"plugin.json"}
    assert {v.file_path.parent.name for v in check(broken)} == {".grok-plugin"}


def test_check_overrides_off_keeps_the_path_checks(temp_dir) -> None:
    """A repository that deliberately replaces its conventional directories
    can silence the one finding without losing the rest."""
    repo = write_repo(temp_dir / "overrides-off")
    plugin = write_plugin(
        repo / "plugins" / "tide-charts", {**MANIFEST, "skills": ["./extra-skills", "./nope"]}
    )
    for directory in ("skills/tide-window", "extra-skills/tide-legend"):
        (plugin / directory).mkdir(parents=True)
        (plugin / directory / "SKILL.md").write_text(SKILL, encoding="utf-8")

    found = messages(check(repo, {"check-overrides": False}))

    assert not any("replaces" in message for message in found)
    assert "'skills': './nope' is not in the plugin" in found


@pytest.mark.parametrize(
    "field,contents",
    [
        pytest.param("skills", {".gitkeep": "", "README.md": "# Skills\n"}, id="skills"),
        pytest.param("commands", {".gitkeep": "", "notes.txt": "not markdown\n"}, id="commands"),
        pytest.param("agents", {"draft/notes.md": "# Draft\n"}, id="agents-nested"),
    ],
)
def test_an_override_beside_a_directory_grok_loads_nothing_from_is_clean(
    temp_dir, field, contents
) -> None:
    """A conventional directory holding a README, a ``.gitkeep`` or a nested
    tree loads nothing, so an override displaces nothing. The conventional
    scan is one level deep and reads ``SKILL.md`` for skills, flat ``*.md``
    for the two prose fields."""
    repo = write_repo(temp_dir / f"empty-of-components-{field}")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, field: f"desk-{field}"})
    (plugin / f"desk-{field}").mkdir()
    (plugin / f"desk-{field}" / "note.md").write_text("---\ndescription: A note\n---\n\n# Note\n")
    for relative_path, body in contents.items():
        target = plugin / field / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    assert [m for m in messages(check(repo)) if "replaces" in m] == []


def test_a_declaration_covering_the_conventional_directory_displaces_nothing(temp_dir) -> None:
    """A declared ancestor still loads what the conventional scan would."""
    repo = write_repo(temp_dir / "covered")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, "skills": "./skills"})
    (plugin / "skills" / "tide-window").mkdir(parents=True)
    (plugin / "skills" / "tide-window" / "SKILL.md").write_text(SKILL, encoding="utf-8")

    assert [m for m in messages(check(repo)) if "replaces" in m] == []


def test_a_skills_directory_symlinked_out_of_the_plugin_displaces_nothing(temp_dir) -> None:
    """Grok drops the escaping directory itself, so an override costs
    nothing — and nothing here lists a directory outside the checkout."""
    repo = write_repo(temp_dir / "escaping-conventional")
    outside = temp_dir / "outside" / "skills"
    (outside / "borrowed").mkdir(parents=True)
    (outside / "borrowed" / "SKILL.md").write_text(SKILL, encoding="utf-8")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, "skills": "./extra"})
    (plugin / "extra" / "tide-window").mkdir(parents=True)
    (plugin / "extra" / "tide-window" / "SKILL.md").write_text(SKILL, encoding="utf-8")
    (plugin / "skills").symlink_to(outside)

    assert [m for m in messages(check(repo)) if "replaces" in m] == []


@pytest.mark.parametrize(
    "declared,reported",
    [
        pytest.param({"Stop": []}, False, id="inline-object"),
        pytest.param(42, False, id="number"),
        pytest.param(["ok", 7], True, id="list-with-a-non-string"),
    ],
)
def test_a_declared_value_the_loader_has_no_arm_for_is_left_alone(
    temp_dir, declared, reported
) -> None:
    """Two silences, pinned apart: an inline ``hooks`` object is the
    component itself, and a value neither arm reads is a shape nothing
    measured — reporting either would name a defect that may not exist. A
    *list* still has its string elements read."""
    field = "hooks" if isinstance(declared, dict) else "skills"
    repo = plugin_repo(temp_dir, f"arm-{reported}-{field}", {**MANIFEST, field: declared})

    found = [m for m in messages(check(repo)) if f"'{field}'" in m]

    assert bool(found) is reported
    if reported:
        assert found == ["'skills': 'ok' is not in the plugin"]


def test_an_unreadable_conventional_directory_reports_no_override(temp_dir) -> None:
    """The scan cannot say what would be lost, so it says nothing."""
    repo = write_repo(temp_dir / "unreadable-conventional")
    plugin = write_plugin(repo / "plugins" / "tide-charts", {**MANIFEST, "skills": "./extra"})
    (plugin / "extra" / "tide-window").mkdir(parents=True)
    (plugin / "extra" / "tide-window" / "SKILL.md").write_text(SKILL, encoding="utf-8")
    conventional = plugin / "skills"
    (conventional / "tide-window").mkdir(parents=True)
    (conventional / "tide-window" / "SKILL.md").write_text(SKILL, encoding="utf-8")
    conventional.chmod(0o000)
    try:
        found = [m for m in messages(check(repo)) if "replaces" in m]
    finally:
        conventional.chmod(0o755)

    assert found == []
