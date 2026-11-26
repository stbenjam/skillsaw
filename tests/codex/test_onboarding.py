"""Optional onboarding references follow the selected Codex overlay."""

import json
from pathlib import Path
import shutil

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.discovery.codex import codex_bundles_skill
from skillsaw.rule import Severity
from skillsaw.rules.builtin.codex import CodexPluginJsonValidRule
from skillsaw.utils import invalidate_read_caches

from ._helpers import copy_fixture


def _plugin(tmp_path, layout="portable"):
    repo = copy_fixture("codex/onboarding", tmp_path)
    manifest = repo / "plugin.json"
    if layout == "legacy":
        manifest.unlink()
        manifest = repo / ".codex-plugin/plugin.json"
    elif layout == "fallback":
        data = json.loads(manifest.read_text())
        data.pop("extensions")
        manifest.write_text(json.dumps(data))
        manifest = repo / ".codex-plugin/plugin.json"
    return repo, manifest


def _set_reference(manifest, value):
    data = json.loads(manifest.read_text())
    data.setdefault("extensions", {}).setdefault("com.openai", {})["onboardingSkill"] = value
    manifest.write_text(json.dumps(data))


def _check(repo, config=None):
    invalidate_read_caches()
    return CodexPluginJsonValidRule(config or {}).check(RepositoryContext(repo))


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
@pytest.mark.parametrize("prefix", ["./", ""])
def test_valid_reference_with_non_setup_name(tmp_path, layout, prefix):
    repo, manifest = _plugin(tmp_path, layout)
    _set_reference(manifest, f"{prefix}skills/connect-account/SKILL.md")
    assert _check(repo) == []


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
def test_optional_field_can_be_absent(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    data = json.loads(manifest.read_text())
    data["extensions"]["com.openai"].pop("onboardingSkill")
    manifest.write_text(json.dumps(data))
    assert _check(repo) == []


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
@pytest.mark.parametrize("value", [None, False, 7, [], {}, ["./skills/get-started/SKILL.md"], ""])
def test_malformed_declared_reference(tmp_path, layout, value):
    repo, manifest = _plugin(tmp_path, layout)
    _set_reference(manifest, value)
    findings = _check(repo)
    assert len(findings) == 1
    assert findings[0].file_path == manifest
    assert "non-empty path string" in findings[0].message


@pytest.mark.parametrize("extension", [{}, {"onboardingSkill": "./skills/get-started/SKILL.md"}])
def test_inline_object_shadows_invalid_fallback(tmp_path, extension):
    repo, manifest = _plugin(tmp_path)
    data = json.loads(manifest.read_text())
    data["extensions"]["com.openai"] = extension
    manifest.write_text(json.dumps(data))
    _set_reference(repo / ".codex-plugin/plugin.json", {"invalid": True})
    assert _check(repo) == []


@pytest.mark.parametrize("value", [None, [], False, "ignored"])
def test_non_object_inline_extension_uses_fallback(tmp_path, value):
    repo, manifest = _plugin(tmp_path)
    data = json.loads(manifest.read_text())
    data["extensions"]["com.openai"] = value
    manifest.write_text(json.dumps(data))
    fallback = repo / ".codex-plugin/plugin.json"
    _set_reference(fallback, "./skills/missing/SKILL.md")
    findings = _check(repo)
    assert len(findings) == 1 and findings[0].file_path == fallback


def test_invalid_inline_value_does_not_fall_back(tmp_path):
    repo, manifest = _plugin(tmp_path)
    _set_reference(manifest, False)
    findings = _check(repo)
    assert len(findings) == 1 and findings[0].file_path == manifest


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
@pytest.mark.parametrize(
    "target",
    ["skills/missing/SKILL.md", "skills/get-started", "notes.md", "private/example/SKILL.md"],
)
def test_missing_directory_nonskill_and_unbundled_targets(tmp_path, layout, target):
    repo, manifest = _plugin(tmp_path, layout)
    (repo / "notes.md").write_text("# Meeting notes\n")
    shutil.copytree(repo / "skills/get-started", repo / "private/example")
    _set_reference(manifest, f"./{target}")
    findings = _check(repo)
    assert len(findings) == 1
    assert findings[0].file_path == manifest
    assert "SKILL.md" in findings[0].message


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
def test_custom_component_root_only_applies_to_legacy(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    shutil.copytree(repo / "skills/get-started", repo / "workflows/welcome")
    data = json.loads(manifest.read_text())
    data["skills"] = "./workflows"
    data["extensions"]["com.openai"]["skills"] = "./workflows"
    manifest.write_text(json.dumps(data))
    _set_reference(manifest, "./workflows/welcome/SKILL.md")
    findings = _check(repo)
    assert len(findings) == (0 if layout == "legacy" else 1)


@pytest.mark.parametrize("declared", ["./workflows", "./missing", ["./workflows"]])
def test_legacy_declared_roots_replace_conventional_root(tmp_path, declared):
    repo, manifest = _plugin(tmp_path, "legacy")
    shutil.copytree(repo / "skills/get-started", repo / "workflows/welcome")
    data = json.loads(manifest.read_text())
    data["skills"] = declared
    manifest.write_text(json.dumps(data))
    findings = [v for v in _check(repo) if "onboardingSkill" in v.message]
    assert len(findings) == 1 and "not a bundled skill" in findings[0].message


@pytest.mark.parametrize("absent", [True, False])
def test_legacy_without_declared_paths_uses_conventional_root(tmp_path, absent):
    repo, manifest = _plugin(tmp_path, "legacy")
    data = json.loads(manifest.read_text())
    if absent:
        data.pop("skills")
    else:
        data["skills"] = []
    manifest.write_text(json.dumps(data))
    assert _check(repo) == []


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
def test_shared_claude_manifest_does_not_change_codex_membership(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    marker = repo / ".claude-plugin"
    marker.mkdir()
    (marker / "plugin.json").write_text('{"name": "workspace-notes"}')
    assert RepositoryContext(repo).provenance(repo).claude
    assert _check(repo) == []
    shutil.copytree(repo / "skills/get-started", repo / "skills/private/nested")
    _set_reference(manifest, "./skills/private/nested/SKILL.md")
    assert len(_check(repo)) == (0 if layout == "legacy" else 1)


@pytest.mark.parametrize(
    "value",
    [
        "../outside/SKILL.md",
        "/outside/SKILL.md",
        "./skills/../skills/get-started/SKILL.md",
        "./bad\x00path",
        "C:\\outside\\SKILL.md",
    ],
)
def test_unsafe_paths(tmp_path, value):
    repo, manifest = _plugin(tmp_path)
    _set_reference(manifest, value)
    findings = _check(repo)
    assert len(findings) == 1 and findings[0].file_path == manifest


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
@pytest.mark.parametrize("value", [".//skills/get-started/SKILL.md", "./"])
def test_prefix_is_validated_before_normalization(tmp_path, layout, value):
    repo, manifest = _plugin(tmp_path, layout)
    _set_reference(manifest, value)
    findings = _check(repo, {"check-paths-exist": False})
    assert len(findings) == 1 and findings[0].file_path == manifest


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
@pytest.mark.parametrize("kind", ["directory", "file", "dangling", "loop"])
def test_symlink_escapes_and_unresolvable_targets(tmp_path, layout, kind):
    repo, manifest = _plugin(tmp_path, layout)
    skill = repo / "skills/get-started"
    target = skill if kind == "directory" else skill / "SKILL.md"
    outside = tmp_path / "outside"
    target.rename(outside)
    destination = (
        target if kind == "loop" else tmp_path / "missing" if kind == "dangling" else outside
    )
    target.symlink_to(destination, target_is_directory=kind == "directory")
    _set_reference(manifest, "./skills/get-started/SKILL.md")
    findings = _check(repo)
    assert len(findings) == 1 and findings[0].file_path == manifest


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
def test_contained_file_alias_matches_canonical_skill_identity(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    (repo / "welcome.md").symlink_to(repo / "skills/get-started/SKILL.md")
    _set_reference(manifest, "./welcome.md")
    assert _check(repo) == []


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
def test_hidden_skill_is_not_an_onboarding_target(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    shutil.copytree(repo / "skills/get-started", repo / "skills/.private")
    _set_reference(manifest, "./skills/.private/SKILL.md")
    findings = _check(repo)
    assert len(findings) == 1 and "not a bundled skill" in findings[0].message


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
def test_contained_directory_alias_is_a_bundled_skill(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    (repo / "skills/welcome").symlink_to(repo / "skills/get-started", target_is_directory=True)
    _set_reference(manifest, "./skills/welcome/SKILL.md")
    assert _check(repo) == []


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
@pytest.mark.parametrize("reference_alias", [True, False])
def test_directory_alias_outside_component_still_bundles_skill(tmp_path, layout, reference_alias):
    repo, manifest = _plugin(tmp_path, layout)
    original = repo / "skills/get-started"
    destination = repo / "resources/get-started"
    destination.parent.mkdir()
    original.rename(destination)
    original.symlink_to("../resources/get-started", target_is_directory=True)
    target = "skills/get-started" if reference_alias else "resources/get-started"
    _set_reference(manifest, f"./{target}/SKILL.md")
    assert _check(repo) == []


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
def test_file_symlink_does_not_establish_skill_membership(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    entrypoint = repo / "skills/get-started/SKILL.md"
    entrypoint.rename(repo / "welcome.md")
    entrypoint.symlink_to("../../welcome.md")
    _set_reference(manifest, "./skills/get-started/SKILL.md")
    findings = _check(repo)
    assert len(findings) == 1 and "not a bundled skill" in findings[0].message


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
def test_nested_skill_beneath_a_skill_is_legacy_only(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    shutil.copytree(repo / "skills/connect-account", repo / "skills/get-started/connect-account")
    _set_reference(manifest, "./skills/get-started/connect-account/SKILL.md")
    assert len(_check(repo)) == (0 if layout == "legacy" else 1)


def test_hidden_editor_skill_does_not_establish_codex_membership(tmp_path):
    repo, manifest = _plugin(tmp_path, "legacy")
    target = "skills/group/.agents/skills/get-started"
    shutil.copytree(repo / "skills/get-started", repo / target)
    _set_reference(manifest, f"./{target}/SKILL.md")
    findings = _check(repo)
    assert len(findings) == 1 and "not a bundled skill" in findings[0].message


@pytest.mark.parametrize("depth", [0, 6, 7])
def test_legacy_recursive_skill_depth_limit(tmp_path, depth):
    repo, manifest = _plugin(tmp_path, "legacy")
    target = repo / "skills"
    for _ in range(depth):
        target = target / "nested"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repo / "skills/get-started/SKILL.md", target / "SKILL.md")
    _set_reference(manifest, f"./{target.relative_to(repo)}/SKILL.md")
    assert len(_check(repo)) == (1 if depth == 7 else 0)


def test_legacy_directory_cycle_does_not_establish_membership(tmp_path):
    repo, manifest = _plugin(tmp_path, "legacy")
    (repo / "skills/cycle").symlink_to(".", target_is_directory=True)
    shutil.copytree(repo / "skills/get-started", repo / "private/get-started")
    _set_reference(manifest, "./private/get-started/SKILL.md")
    findings = _check(repo)
    assert len(findings) == 1 and "not a bundled skill" in findings[0].message


@pytest.mark.parametrize("layout", ["portable", "fallback", "legacy"])
def test_alias_to_search_root_does_not_create_a_portable_child_skill(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    shutil.copyfile(repo / "skills/get-started/SKILL.md", repo / "skills/SKILL.md")
    (repo / "skills/self").symlink_to(".", target_is_directory=True)
    _set_reference(manifest, "./skills/self/SKILL.md")
    assert len(_check(repo)) == (0 if layout == "legacy" else 1)


def test_unreadable_legacy_component_does_not_prove_absence(tmp_path, monkeypatch):
    repo, manifest = _plugin(tmp_path, "legacy")
    blocked = repo / "blocked"
    blocked.mkdir()
    data = json.loads(manifest.read_text())
    data["skills"] = ["./blocked", "./skills"]
    manifest.write_text(json.dumps(data))
    shutil.copytree(repo / "skills/get-started", repo / "private/get-started")
    known = (repo / "skills/get-started/SKILL.md").resolve()
    unbundled = (repo / "private/get-started/SKILL.md").resolve()
    iterdir = Path.iterdir

    def read_directory(path):
        if path == blocked:
            raise PermissionError("Cannot read the component")
        return iterdir(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "iterdir", read_directory)
        assert codex_bundles_skill(repo, known, portable=False) is True
        assert codex_bundles_skill(repo, unbundled, portable=False) is None
        _set_reference(manifest, "./private/get-started/SKILL.md")
        assert _check(repo) == []
    findings = _check(repo)
    assert len(findings) == 1 and "not a bundled skill" in findings[0].message


@pytest.mark.parametrize("directories,limit", [(True, 1_999), (False, 20_000)])
def test_legacy_scan_count_limits_do_not_prove_absence(tmp_path, directories, limit):
    repo, manifest = _plugin(tmp_path, "legacy")
    component = repo / "components"
    component.mkdir()
    data = json.loads(manifest.read_text())
    data["skills"] = "./components"
    manifest.write_text(json.dumps(data))
    for index in range(limit):
        entry = component / f"entry-{index:05}"
        entry.mkdir() if directories else entry.touch()
    target = (repo / "skills/get-started/SKILL.md").resolve()
    assert codex_bundles_skill(repo, target, portable=False) is False
    extra = component / "one-too-many"
    extra.mkdir() if directories else extra.touch()
    assert codex_bundles_skill(repo, target, portable=False) is None


@pytest.mark.parametrize("layout", ["portable", "legacy"])
def test_excluded_skill_does_not_become_an_unbundled_finding(tmp_path, layout):
    repo, manifest = _plugin(tmp_path, layout)
    _set_reference(manifest, "./skills/get-started/SKILL.md")
    context = RepositoryContext(repo, exclude_patterns=["skills/get-started/**"])
    assert CodexPluginJsonValidRule({}).check(context) == []


def test_check_paths_exist_setting_and_severity_override(tmp_path):
    repo, manifest = _plugin(tmp_path)
    _set_reference(manifest, "./skills/generated/SKILL.md")
    assert _check(repo, {"check-paths-exist": False}) == []
    findings = _check(repo, {"severity": "warning"})
    assert len(findings) == 1 and findings[0].severity == Severity.WARNING
    _set_reference(manifest, "../outside/SKILL.md")
    assert len(_check(repo, {"check-paths-exist": False})) == 1


def test_installed_manifest_keeps_existing_stand_down(tmp_path):
    source, manifest = _plugin(tmp_path)
    _set_reference(manifest, False)
    repo = tmp_path / "installed"
    installed = repo / ".codex/plugins/workspace-notes"
    installed.parent.mkdir(parents=True)
    source.rename(installed)
    assert _check(repo) == []
