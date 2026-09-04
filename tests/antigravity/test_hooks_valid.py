"""``antigravity-hooks-valid``: the two load-time failure scopes.

Every ERROR below drops the whole file in ``agy`` and still exits 0; every
WARNING is a key ``agy`` ignores, so the hook it configures never runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.antigravity.hooks_valid import AntigravityHooksValidRule

from ._helpers import at, messages, only, repo_with_hooks, run_rule

WORKING = (
    '{"audit": {"PreToolUse": [{"matcher": "run_command", "hooks": [{"command": "./x.sh"}]}]}}'
)


def check(tmp_path: Path, name: str, body: str, config=None, dirname: str = ".agents"):
    repo = repo_with_hooks(tmp_path, name, body, dirname)
    return run_rule(AntigravityHooksValidRule, repo, config)


class TestAcceptedFiles:
    """Files that load, which a rule at ERROR severity must not touch."""

    @pytest.mark.parametrize(
        "name,body",
        [
            ("documented", WORKING),
            ("empty-root", "{}"),
            ("empty-hook", '{"audit": {}}'),
            ("empty-event", '{"audit": {"Stop": []}}'),
            ("empty-group", '{"audit": {"PreToolUse": [{}]}}'),
            ("group-without-hooks", '{"audit": {"PreToolUse": [{"matcher": "*"}]}}'),
            ("unnamed-hook", '{"": {"Stop": [{"command": "make lint"}]}}'),
            # ``type`` absent, or empty, is a command hook.
            ("no-type", '{"audit": {"Stop": [{"command": "make lint"}]}}'),
            ("empty-type", '{"audit": {"Stop": [{"type": "", "command": "make lint"}]}}'),
            ("prompt-type", '{"audit": {"Stop": [{"type": "prompt", "prompt": "Check UTC."}]}}'),
            ("prompt-without-text", '{"audit": {"Stop": [{"type": "prompt"}]}}'),
            # ``timeout`` is an int32; zero, negatives and both ends load.
            ("timeout-zero", '{"audit": {"Stop": [{"command": "x", "timeout": 0}]}}'),
            ("timeout-negative", '{"audit": {"Stop": [{"command": "x", "timeout": -5}]}}'),
            ("timeout-max", '{"audit": {"Stop": [{"command": "x", "timeout": 2147483647}]}}'),
            ("timeout-min", '{"audit": {"Stop": [{"command": "x", "timeout": -2147483648}]}}'),
            # Event keys bind case-insensitively.
            ("lowercase-event", '{"audit": {"pretooluse": [{"hooks": []}]}}'),
            ("uppercase-event", '{"audit": {"STOP": [{"command": "make lint"}]}}'),
            # ``SessionStart`` is undocumented and real.
            ("session-start", '{"audit": {"SessionStart": [{"command": "make status"}]}}'),
            # A hook-level switch is documented and valid.
            ("hook-disabled", '{"audit": {"enabled": false, "Stop": [{"command": "x"}]}}'),
            # ``matcher`` is never compiled at load time.
            ("wildcard-star", '{"a": {"PreToolUse": [{"matcher": "*", "hooks": []}]}}'),
            ("wildcard-empty", '{"a": {"PreToolUse": [{"matcher": "", "hooks": []}]}}'),
            ("invalid-regex", '{"a": {"PreToolUse": [{"matcher": "[unclosed", "hooks": []}]}}'),
            ("js-named-group", '{"a": {"PreToolUse": [{"matcher": "(?<t>run_.*)", "hooks": []}]}}'),
            ("unicode-class", '{"a": {"PreToolUse": [{"matcher": "\\\\p{L}+", "hooks": []}]}}'),
            ("lookahead", '{"a": {"PreToolUse": [{"matcher": "run_(?!x)", "hooks": []}]}}'),
            (
                "long-matcher",
                '{"a": {"PreToolUse": [{"matcher": "%s", "hooks": []}]}}' % ("x" * 4000),
            ),
        ],
    )
    def test_no_findings(self, tmp_path: Path, name: str, body: str) -> None:
        assert messages(check(tmp_path, name, body)) == []


class TestFileScopedDefects:
    """One defect, and a message that says the whole file stops loading."""

    @pytest.mark.parametrize(
        "name,body,needle",
        [
            ("bad-json", '{"audit": }', "does not parse"),
            ("array-root", "[]", "must be a JSON object of named hooks"),
            ("string-root", '"make lint"', "must be a JSON object of named hooks"),
            (
                "non-finite",
                '{"a": {"Stop": [{"command": "x", "timeout": 1e400}]}}',
                "not valid JSON",
            ),
            ("file-enabled", '{"enabled": false}', "is read as a hook name, not a switch"),
            ("hook-not-object", '{"audit": "make lint"}', "a named hook must be a JSON object"),
            (
                "enabled-not-bool",
                '{"audit": {"enabled": "no", "Stop": []}}',
                "'enabled' must be a boolean",
            ),
            (
                "event-not-array",
                '{"audit": {"PreToolUse": {"matcher": "*"}}}',
                "an event's value must be an array",
            ),
            (
                "group-not-object",
                '{"audit": {"PreToolUse": ["make lint"]}}',
                "a hook group must be a JSON object",
            ),
            (
                "handler-not-object",
                '{"audit": {"Stop": ["make lint"]}}',
                "a handler must be a JSON object",
            ),
            (
                "nested-handler-not-object",
                '{"audit": {"PreToolUse": [{"hooks": ["make lint"]}]}}',
                "a handler must be a JSON object",
            ),
            (
                "matcher-not-string",
                '{"audit": {"PreToolUse": [{"matcher": 5, "hooks": []}]}}',
                "'matcher' must be a string",
            ),
            (
                "hooks-not-array",
                '{"audit": {"PreToolUse": [{"hooks": "make lint"}]}}',
                "'hooks' must be an array of handlers",
            ),
            (
                "shouting-type",
                '{"audit": {"Stop": [{"type": "COMMAND", "command": "x"}]}}',
                "handler type 'COMMAND' is not supported",
            ),
            (
                "unknown-type",
                '{"audit": {"Stop": [{"type": "http", "command": "x"}]}}',
                "handler type 'http' is not supported",
            ),
            (
                "type-not-string",
                '{"audit": {"Stop": [{"type": 5, "command": "x"}]}}',
                "'type' must be a string",
            ),
            (
                "command-with-prompt",
                '{"audit": {"Stop": [{"command": "x", "prompt": "hi"}]}}',
                "a command hook may not carry 'prompt'",
            ),
            (
                "command-with-model",
                '{"audit": {"Stop": [{"command": "x", "model": "gemini-3-pro"}]}}',
                "a command hook may not carry 'model'",
            ),
            (
                "prompt-with-command",
                '{"audit": {"Stop": [{"type": "prompt", "command": "x"}]}}',
                "a prompt hook may not carry 'command'",
            ),
            (
                "fractional-timeout",
                '{"audit": {"Stop": [{"command": "x", "timeout": 1.5}]}}',
                "'timeout' must be a whole number of seconds",
            ),
            (
                "string-timeout",
                '{"audit": {"Stop": [{"command": "x", "timeout": "10"}]}}',
                "'timeout' must be a whole number of seconds",
            ),
            (
                "boolean-timeout",
                '{"audit": {"Stop": [{"command": "x", "timeout": true}]}}',
                "'timeout' must be a whole number of seconds",
            ),
            # Measured: an integer past either end of the int32 range empties
            # the file exactly as a float does.
            (
                "timeout-over-int32",
                '{"audit": {"Stop": [{"command": "x", "timeout": 1099511627776}]}}',
                "'timeout' must be between -2147483648 and 2147483647",
            ),
            (
                "timeout-under-int32",
                '{"audit": {"Stop": [{"command": "x", "timeout": -2147483649}]}}',
                "'timeout' must be between -2147483648 and 2147483647",
            ),
            (
                "command-not-string",
                '{"audit": {"Stop": [{"command": ["curl", "x"]}]}}',
                "'command' must be a string",
            ),
        ],
    )
    def test_reported_at_error(self, tmp_path: Path, name: str, body: str, needle: str) -> None:
        violations = check(tmp_path, name, body)
        found = only(violations, needle)
        assert found.severity == Severity.ERROR

    def test_message_names_the_scope(self, tmp_path: Path) -> None:
        violations = check(
            tmp_path, "scope", '{"audit": {"Stop": [{"command": "x", "timeout": 1.5}]}}'
        )
        assert messages(violations) == [
            "hook 'audit' Stop[0]: 'timeout' must be a whole number of seconds; "
            "Antigravity loads no hook from this file"
        ]


class TestIgnoredKeys:
    """Silently ignored at load, so the hook never runs."""

    @pytest.mark.parametrize(
        "name,body,needle",
        [
            (
                "unknown-event",
                '{"audit": {"SessionEnd": [{"command": "x"}]}}',
                "event 'SessionEnd' is not one Antigravity dispatches",
            ),
            (
                "unknown-handler-key",
                '{"audit": {"Stop": [{"command": "x", "background": true}]}}',
                "unknown handler key 'background' is ignored",
            ),
            (
                "unknown-group-key",
                '{"a": {"PreToolUse": [{"description": "d", "hooks": []}]}}',
                "unknown group key 'description' is ignored",
            ),
            (
                "no-command",
                '{"audit": {"Stop": [{"type": "command"}]}}',
                "a command hook with no command runs nothing",
            ),
            (
                "empty-command",
                '{"audit": {"Stop": [{"command": ""}]}}',
                "a command hook with no command runs nothing",
            ),
            # A flat event has no matcher, so one written there filters nothing.
            (
                "matcher-on-flat-event",
                '{"audit": {"Stop": [{"matcher": "x", "command": "make lint"}]}}',
                "unknown handler key 'matcher' is ignored",
            ),
        ],
    )
    def test_reported_at_warning(self, tmp_path: Path, name: str, body: str, needle: str) -> None:
        violations = check(tmp_path, name, body)
        found = only(violations, needle)
        assert found.severity == Severity.WARNING

    def test_several_unknown_keys_consolidate(self, tmp_path: Path) -> None:
        violations = check(
            tmp_path,
            "many-unknown",
            '{"audit": {"Stop": [{"command": "x", "background": true, "cwd": "/srv"}]}}',
        )
        assert messages(violations) == [
            "hook 'audit' Stop[0]: unknown handler keys 'background', 'cwd' are ignored"
        ]

    def test_advisories_wait_for_a_loadable_file(self, tmp_path: Path) -> None:
        """Nothing loads while a file-scoped defect stands, so nothing is ignored yet."""
        violations = check(
            tmp_path,
            "both",
            '{"audit": {"Stop": [{"command": "x", "timeout": 1.5, "background": true}]}}',
        )
        assert at(violations, Severity.WARNING) == []
        assert len(at(violations, Severity.ERROR)) == 1


class TestExtraEvents:
    """The escape hatch for an event newer than this release."""

    def test_declared_event_is_accepted(self, tmp_path: Path) -> None:
        body = '{"audit": {"SessionEnd": [{"command": "x"}]}}'
        config = {"extra-events": ["SessionEnd"]}
        assert messages(check(tmp_path, "extra", body, config)) == []

    def test_declared_event_matches_case_insensitively(self, tmp_path: Path) -> None:
        body = '{"audit": {"sessionend": [{"command": "x"}]}}'
        config = {"extra-events": ["SessionEnd"]}
        assert messages(check(tmp_path, "extra-case", body, config)) == []

    @pytest.mark.parametrize("value", ("SessionEnd", 42, {"SessionEnd": True}, [["SessionEnd"]]))
    def test_wrong_type_costs_no_findings(self, tmp_path: Path, value) -> None:
        """A bad config line must not take every hooks finding with it."""
        body = '{"audit": {"Stop": [{"command": "x", "timeout": 1.5}]}}'
        violations = check(
            tmp_path, f"coerce-{type(value).__name__}", body, {"extra-events": value}
        )
        assert len(violations) == 1


class TestEveryRoot:
    """The rule reads all four customization roots and a plugin's own file."""

    @pytest.mark.parametrize("dirname", (".agents", ".agent", "_agents", "_agent"))
    def test_each_root(self, tmp_path: Path, dirname: str) -> None:
        violations = check(tmp_path, f"root-{dirname.lstrip('._')}", "[]", dirname=dirname)
        assert len(violations) == 1

    def test_plugin_hooks_file(self, tmp_path: Path) -> None:
        from ._helpers import write_plugin, write_repo

        repo = write_repo(tmp_path / "plugin-hooks")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        (plugin / "hooks.json").write_text("[]", encoding="utf-8")
        violations = run_rule(AntigravityHooksValidRule, repo)
        assert len(violations) == 1
        assert violations[0].file_path == plugin / "hooks.json"


class TestGating:
    """``auto``, and only where Antigravity content lives."""

    def test_rule_declares_the_release_it_shipped_in(self) -> None:
        assert AntigravityHooksValidRule.since == "0.20.0"
        assert AntigravityHooksValidRule.default_enabled == "auto"

    def test_repo_types(self) -> None:
        assert AntigravityHooksValidRule.repo_types == frozenset(
            {RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN}
        )
