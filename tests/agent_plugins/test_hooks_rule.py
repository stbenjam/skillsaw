"""Portable hooks failure scopes, package boundaries and shared inspection."""

import json
from pathlib import Path

import pytest

from tests.cli_runner import run_cli

from ._helpers import copy_fixture

RULE = "agent-plugin-hooks-valid"


@pytest.fixture
def package(tmp_path):
    return copy_fixture("agent-plugins/hooks-1.1", tmp_path)


def lint(package, rule=RULE):
    result = run_cli(["lint", str(package), "--rule", rule, "--format", "json"])
    findings = json.loads(result.stdout)["violations"]
    assert result.returncode == bool(findings)
    assert all(item["rule_id"] == rule for item in findings)
    return [item["message"] for item in findings]


def hooks(package, events, **extra):
    data = {"$schema": "https://agent-plugins.org/schemas/1.1.0/hooks.schema.json", "hooks": events}
    (package / "hooks.json").write_text(json.dumps({**data, **extra}))


def test_fixture_and_shared_security_view(package):
    assert lint(package) == []
    messages = lint(package, "hooks-prohibited")
    assert any("release-review --context" in message for message in messages)
    assert any("./bin/finish-review" in message for message in messages)


def test_components_are_version_gated(package):
    manifest = package / "plugin.json"
    manifest.write_text(manifest.read_text().replace("1.1.0", "1.0.0"))
    (package / "hooks.json").write_text("invalid")
    assert lint(package) == []
    assert lint(package, "hooks-prohibited") == []


def test_event_and_handler_failures_are_independent(package):
    hooks(
        package,
        {
            "SessionStart": [],
            "UnknownEvent": [{"command": "unused"}],
            "PreToolUse": [
                {"command": "./../outside"},
                {"command": "release-review", "args": [42]},
                {"command": "release-review", "extensions": {"com.example": []}},
                {"command": "release-review"},
            ],
        },
    )
    messages = lint(package)
    assert len(messages) == 5
    for key in ["SessionStart", "UnknownEvent", "PreToolUse[0]", "PreToolUse[1]", "PreToolUse[2]"]:
        assert any(key in message for message in messages)


def test_top_level_failure_precedes_event_failures(package):
    hooks(
        package,
        {"Unknown": []},
        **{"$schema": "https://agent-plugins.org/schemas/1.0.0/hooks.schema.json"},
    )
    (message,) = lint(package)
    assert "$schema" in message and "Unknown" not in message


def test_optional_and_empty_hooks(package):
    hooks(package, {})
    assert lint(package) == []
    (package / "hooks.json").unlink()
    assert lint(package) == []


@pytest.mark.parametrize("text", ["null", "{}", '{"hooks": {}, "hooks": {}}', "{"])
def test_invalid_documents(package, text):
    (package / "hooks.json").write_text(text)
    assert len(lint(package)) == 1


@pytest.mark.parametrize("kind", ["directory", "external", "dangling"])
def test_component_must_be_a_contained_regular_file(package, tmp_path, kind):
    path = package / "hooks.json"
    path.unlink()
    if kind == "directory":
        path.mkdir()
    elif kind == "external":
        outside = tmp_path / "outside.json"
        outside.write_text("external contents")
        path.symlink_to(outside)
    else:
        path.symlink_to("absent.json")
    (message,) = lint(package)
    assert "regular file inside the plugin root" in message
    assert lint(package, "hooks-prohibited") == []


def test_contained_hook_file_symlink_resolves_commands_from_package_root(package):
    path = package / "hooks.json"
    directory = package / "configs"
    directory.mkdir()
    path.rename(directory / "portable.json")
    path.symlink_to(Path("configs") / "portable.json")
    (package / "bin").symlink_to(package.parent, target_is_directory=True)
    (message,) = lint(package)
    assert "Stop[0]" in message and "outside the plugin root" in message


def test_malformed_args_keep_the_command_visible_to_security_rules(package):
    hooks(package, {"Stop": [{"command": "release-review", "args": [42, "--fast"]}]})
    (message,) = lint(package)
    assert "Stop[0]" in message
    assert any("release-review --fast" in message for message in lint(package, "hooks-prohibited"))


def test_shared_hooks_file_checks_commands_against_each_plugin_root(package):
    inner = package / "plugins" / "inner"
    inner.mkdir(parents=True)
    (inner / "plugin.json").write_text((package / "plugin.json").read_text())
    hooks(package, {"Stop": [{"command": "./bin/run"}, {"command": "./../escape"}]})
    (package / "hooks.json").rename(inner / "hooks.json")
    (package / "hooks.json").symlink_to(Path("plugins") / "inner" / "hooks.json")
    # Inside the outer root, but outside the inner plugin that declares it.
    (inner / "bin").symlink_to(package, target_is_directory=True)
    messages = lint(package)
    assert len(messages) == 2
    assert any("Stop[0]" in message and "outside" in message for message in messages)
    assert any("Stop[1]" in message and "outside" in message for message in messages)
