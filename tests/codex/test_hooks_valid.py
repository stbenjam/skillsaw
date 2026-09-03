"""``codex-hooks-valid`` — Codex's own hook events, handler types and fields.

Codex adopted Claude Code's nested hooks shape and kept none of its
vocabulary, so a hooks file copied from a Claude plugin loads without
complaint and does less than it says. These tests drive the two fixtures
that pin that: ``codex/hooks-valid`` collects one instance of each finding
the rule makes, and ``codex/hooks-clean`` is the same layout written the
way Codex reads it.
"""

import json

import pytest

from skillsaw.blocks import ClaudeHooksBlock, CodexHooksBlock
from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.codex import CodexHooksValidRule
from skillsaw.rules.builtin.hooks import ClaudeHooksValidRule, HooksDangerousRule
from tests.cli_runner import run_cli

from ._helpers import copy_fixture, messages


def _findings(repo, config=None):
    return CodexHooksValidRule(config or {}).check(RepositoryContext(repo))


def _root_hooks_repo(tmp_path, document):
    """A project-layer ``.codex/hooks.json``, the location Codex documents.

    Written per test rather than fixtured: these cases are single malformed
    values, and one file each keeps the failure readable.
    """
    repo = tmp_path / "repo"
    (repo / ".codex").mkdir(parents=True)
    (repo / "AGENTS.md").write_text(
        "# Service\n\nRun `make test` before opening a pull request.\n", encoding="utf-8"
    )
    (repo / ".codex" / "hooks.json").write_text(
        document if isinstance(document, str) else json.dumps(document, indent=2),
        encoding="utf-8",
    )
    return repo


def _one_command_hook(event, handler):
    return {"hooks": {event: [{"hooks": [handler]}]}}


# ── Where the blocks come from ──────────────────────────────────


class TestCodexHookLocations:
    """Every file Codex reads hooks from must reach the rule."""

    def test_the_project_layer_hooks_file_is_a_codex_block(self, tmp_path):
        """Codex resolves ``.codex/hooks.json`` from the project root,
        plugin or not — and no other host reads it."""
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        tree = RepositoryContext(repo).lint_tree

        assert repo / ".codex" / "hooks.json" in {b.path for b in tree.find(CodexHooksBlock)}
        assert tree.find(ClaudeHooksBlock) == []

    def test_a_codex_only_plugins_hooks_file_is_a_codex_block(self, tmp_path):
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        tree = RepositoryContext(repo).lint_tree

        assert {b.path.relative_to(repo).as_posix() for b in tree.find(CodexHooksBlock)} == {
            ".codex/hooks.json",
            "plugins/policy-guard/hooks/hooks.json",
        }

    def test_claudes_rule_says_nothing_about_a_codex_hooks_file(self, tmp_path):
        """The split's other half: Claude's vocabulary never judges these."""
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        assert ClaudeHooksValidRule({}).check(RepositoryContext(repo)) == []


# ── The fixture's findings ──────────────────────────────────────


class TestBrokenFixture:
    """One instance of each finding, with the severity it is filed at."""

    @pytest.mark.parametrize(
        "fragment,severity",
        [
            # An event Codex does not dispatch: the file loads, the hook
            # never runs, and Codex reports nothing.
            ("Unknown hook event 'PostToolUseFailure'", Severity.WARNING),
            # ``matcher`` is accepted and ignored outside the events that
            # filter on one — worth knowing, not worth failing a build.
            ("Event 'UserPromptSubmit[0].matcher' is ignored on this event", Severity.INFO),
            # Codex parses ``prompt``/``agent`` handlers and never runs
            # them. Claude Code runs them, so a shared file may carry one.
            ("Event 'SessionStart[0].hooks[0]' has type 'prompt'", Severity.WARNING),
            ("SessionEnd does not support MCP tool hooks", Severity.ERROR),
            ("field 'timeout' is 30s, but Codex caps SessionEnd hooks at 3s", Severity.WARNING),
            ("field 'input' is only valid on types: mcp_tool", Severity.WARNING),
            ("of type 'mcp_tool' requires a 'tool' field", Severity.ERROR),
        ],
    )
    def test_each_check_fires_once(self, tmp_path, fragment, severity):
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        matched = [v for v in _findings(repo) if fragment in v.message]

        assert len(matched) == 1, messages(_findings(repo))
        assert matched[0].severity is severity

    def test_the_fixture_reports_nothing_else(self, tmp_path):
        """A count, so a new check cannot land unnoticed in the fixture."""
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        assert len(_findings(repo)) == 7, messages(_findings(repo))

    def test_findings_carry_no_line_number(self, tmp_path):
        """JSON keeps none, and a fabricated line is worse than none."""
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        assert all(v.line is None for v in _findings(repo))
        assert all(v.file_path is not None for v in _findings(repo))


class TestCleanFixture:
    def test_the_clean_twin_reports_nothing(self, tmp_path):
        repo = copy_fixture("codex/hooks-clean", tmp_path)
        assert _findings(repo) == []

    def test_the_clean_twin_still_has_both_blocks(self, tmp_path):
        """Otherwise the clean result would be vacuous."""
        repo = copy_fixture("codex/hooks-clean", tmp_path)
        blocks = RepositoryContext(repo).lint_tree.find(CodexHooksBlock)
        assert len(blocks) == 2


# ── Structural checks the fixture does not carry ────────────────


class TestStructuralShape:
    """Malformed values that stop hooks loading at all."""

    def test_invalid_json_is_reported(self, tmp_path):
        repo = _root_hooks_repo(tmp_path, '{"hooks": {')
        found = messages(_findings(repo))
        assert any("Invalid JSON" in m for m in found), found

    @pytest.mark.parametrize(
        "document,fragment",
        [
            ([], "must be a JSON object"),
            ({"description": "no hooks here"}, "must contain a 'hooks' key"),
            ({"hooks": []}, "'hooks' must be a JSON object"),
            ({"hooks": {"SessionStart": {"type": "command"}}}, "must have an array"),
            ({"hooks": {"SessionStart": ["echo hi"]}}, "configuration must be an object"),
            ({"hooks": {"SessionStart": [{"matcher": ".*"}]}}, "must have a 'hooks' array"),
            ({"hooks": {"SessionStart": [{"hooks": {}}]}}, "hooks' must be an array"),
            ({"hooks": {"SessionStart": [{"hooks": ["echo"]}]}}, "must be an object"),
            ({"hooks": {"SessionStart": [{"hooks": [{}]}]}}, "must have a 'type' field"),
        ],
    )
    def test_a_malformed_shape_is_reported(self, tmp_path, document, fragment):
        repo = _root_hooks_repo(tmp_path, document)
        found = messages(_findings(repo))
        assert any(fragment in m for m in found), found

    @pytest.mark.parametrize("bad", [[], {}, 42, None])
    def test_a_non_string_matcher_is_reported(self, tmp_path, bad):
        """The block coerces it to the ``.*`` wildcard so the security
        rules still see the commands; reporting keeps the coercion from
        hiding a hook that now fires on everything."""
        repo = _root_hooks_repo(
            tmp_path,
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": bad,
                            "hooks": [{"type": "command", "command": "echo hi"}],
                        }
                    ]
                }
            },
        )
        found = messages(_findings(repo))
        assert any("matcher' must be a string" in m for m in found), found

    @pytest.mark.parametrize("bad", [[], {}, ["command"], 42, "http"])
    def test_an_unknown_handler_type_is_reported_not_raised(self, tmp_path, bad):
        """An unhashable ``type`` would raise ``TypeError`` in the set
        membership test and cost every later block its findings. ``http``
        is Claude Code's, and the likeliest way a real file gets here."""
        repo = _root_hooks_repo(
            tmp_path, _one_command_hook("SessionStart", {"type": bad, "command": "echo hi"})
        )
        found = messages(_findings(repo))
        assert any("invalid type" in m for m in found), found

    def test_a_credentialed_handler_type_is_redacted(self, tmp_path):
        repo = _root_hooks_repo(
            tmp_path,
            _one_command_hook(
                "SessionStart",
                {"type": {"url": "https://user:sekrit123@host.example/x"}, "command": "echo hi"},
            ),
        )
        found = messages(_findings(repo))
        assert any("invalid type" in m for m in found), found
        assert all("sekrit123" not in m for m in found)

    def test_a_missing_required_field_is_reported(self, tmp_path):
        repo = _root_hooks_repo(tmp_path, _one_command_hook("SessionStart", {"type": "command"}))
        found = messages(_findings(repo))
        assert any("requires a 'command' field" in m for m in found), found

    def test_a_non_string_required_field_is_reported(self, tmp_path):
        repo = _root_hooks_repo(
            tmp_path,
            _one_command_hook("SessionStart", {"type": "command", "command": ["echo", "hi"]}),
        )
        found = messages(_findings(repo))
        assert any("field 'command' must be a str" in m for m in found), found

    @pytest.mark.parametrize(
        "field,value,expected",
        [
            ("statusMessage", 42, "must be a str"),
            ("additionalContextLimit", "4096", "must be a int"),
            # ``bool`` is an ``int`` subclass; a limit of ``True`` is not one.
            ("additionalContextLimit", True, "must be a int"),
            ("async", "yes", "must be a bool"),
            ("commandWindows", ["powershell"], "must be a str"),
        ],
    )
    def test_a_mistyped_optional_field_is_reported(self, tmp_path, field, value, expected):
        repo = _root_hooks_repo(
            tmp_path,
            _one_command_hook(
                "SessionStart", {"type": "command", "command": "echo hi", field: value}
            ),
        )
        found = messages(_findings(repo))
        assert any(f"field '{field}' {expected}" in m for m in found), found

    @pytest.mark.parametrize("bad", ["30s", True, [30]])
    def test_a_non_numeric_timeout_is_reported(self, tmp_path, bad):
        repo = _root_hooks_repo(
            tmp_path,
            _one_command_hook(
                "SessionStart", {"type": "command", "command": "echo hi", "timeout": bad}
            ),
        )
        found = messages(_findings(repo))
        assert any("'timeout' must be a number" in m for m in found), found

    def test_a_huge_integer_timeout_is_accepted(self, tmp_path):
        """JSON bounds no integer literal, and converting one to float
        would raise ``OverflowError`` and cost the rule every finding."""
        repo = _root_hooks_repo(
            tmp_path,
            _one_command_hook(
                "SessionStart", {"type": "command", "command": "echo hi", "timeout": 10**400}
            ),
        )
        assert _findings(repo) == []

    def test_entries_under_an_unknown_event_are_still_shape_checked(self, tmp_path):
        """The event may be one this release has not heard of, in which
        case its entries are live configuration."""
        repo = _root_hooks_repo(tmp_path, _one_command_hook("SomethingNew", {"type": "command"}))
        found = messages(_findings(repo))
        assert any("Unknown hook event" in m for m in found), found
        assert any("requires a 'command' field" in m for m in found), found


# ── Configuration ───────────────────────────────────────────────


class TestExtraEvents:
    def test_extra_events_silences_the_unknown_event_warning(self, tmp_path):
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        config = {"extra-events": ["PostToolUseFailure"]}

        assert any("Unknown hook event" in m for m in messages(_findings(repo)))
        assert not any("Unknown hook event" in m for m in messages(_findings(repo, config)))

    def test_a_declared_event_keeps_every_other_finding(self, tmp_path):
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        config = {"extra-events": ["PostToolUseFailure"]}
        assert len(_findings(repo, config)) == len(_findings(repo)) - 1

    @pytest.mark.parametrize("bad", [42, "PostToolUseFailure", None])
    def test_a_wrong_shaped_extra_events_costs_no_other_finding(self, tmp_path, bad):
        """The declared type is not enforced when the config loads.
        Iterating an int would raise and lose every structural finding in
        every Codex hooks file over one bad config line."""
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        assert len(_findings(repo, {"extra-events": bad})) == 7


# ── The security rules read the same blocks ─────────────────────


class TestSecurityRulesReachCodexHooks:
    def test_hooks_dangerous_scans_a_project_layer_hooks_file(self, tmp_path):
        """``.codex/hooks.json`` is executable supply-chain surface, and
        the shared ``HooksBlock`` base is how the security rules find it."""
        repo = copy_fixture("codex/hooks-root-dangerous", tmp_path)
        found = HooksDangerousRule({}).check(RepositoryContext(repo))

        assert any("toolchain.example.com" in v.message for v in found), messages(found)
        assert {v.file_path.name for v in found} == {"hooks.json"}


# ── End to end ──────────────────────────────────────────────────


@pytest.mark.integration
class TestCodexHooksThroughTheCli:
    def _run(self, repo):
        result = run_cli(["lint", "--format", "json", "-v", str(repo)])
        return json.loads(result.stdout)["violations"]

    def test_the_broken_fixture_reports_through_the_cli(self, tmp_path):
        repo = copy_fixture("codex/hooks-valid", tmp_path)
        found = [v for v in self._run(repo) if v["rule_id"] == "codex-hooks-valid"]

        assert len(found) == 7, found
        assert {v["file_path"] for v in found} == {
            ".codex/hooks.json",
            "plugins/policy-guard/hooks/hooks.json",
        }

    def test_the_clean_fixture_reports_nothing_through_the_cli(self, tmp_path):
        repo = copy_fixture("codex/hooks-clean", tmp_path)
        assert [v for v in self._run(repo) if v["rule_id"] == "codex-hooks-valid"] == []
