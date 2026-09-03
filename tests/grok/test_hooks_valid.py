"""``grok-hooks-valid`` — one verdict per defect, at the severity its scope earns.

Every scope below was measured against Grok Build 1.0.13 with a canary
matrix: one hook file per case in an isolated ``GROK_HOME``'s ``hooks/``
directory (user scope, always trusted, so no folder-trust gate), each
handler carrying a unique command token, read back from ``grok inspect
--json``. Each case carries a canary handler in the same group and a canary
group under a different event in the same file, so whole-file, group and
handler scopes are told apart rather than assumed. ``skillsaw.formats.grok``
records the matrix; re-run it before changing a verdict here.
"""

from __future__ import annotations

import codecs
import json
import time

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.linter import Linter
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokHooksValidRule
from tests.grok._helpers import (
    HOOKS_JSON,
    at,
    check,
    copy_fixture,
    lint_json,
    messages,
    only,
    repo_with_hooks,
    violations_for,
    write_hooks,
    write_repo,
)


def hooks_doc(event: str, *handlers: dict, matcher: str | None = None) -> str:
    """One matcher group under *event*, as a JSON document."""
    group: dict = {"hooks": list(handlers)}
    if matcher is not None:
        group["matcher"] = matcher
    return json.dumps({"hooks": {event: [group]}})


# ── Rule metadata ────────────────────────────────────────────────


def test_rule_metadata() -> None:
    rule = GrokHooksValidRule()

    assert rule.rule_id == "grok-hooks-valid"
    assert rule.default_severity() == Severity.ERROR
    assert rule.default_enabled == "auto"
    assert rule.since == "0.20.0"
    assert rule.repo_types == frozenset({RepositoryType.GROK_PROJECT})
    # A tool directory nobody else claims needs no provenance filtering, and
    # the rule reads a file rather than a repository layout.
    assert rule.provenance_scope is None
    assert not rule.supports_autofix
    assert "extra-events" in rule.config_schema


def test_generated_defaults_match_the_class() -> None:
    config = LinterConfig.default().get_rule_config("grok-hooks-valid")

    assert config["enabled"] == "auto"
    assert config["severity"] == "error"


def test_the_rule_is_not_loaded_without_grok_evidence(tmp_path) -> None:
    repo = write_repo(tmp_path / "no-grok")
    context = RepositoryContext(repo)

    assert RepositoryType.GROK_PROJECT not in context.repo_types
    loaded = {rule.rule_id for rule in Linter(context, no_plugins=True).rules}
    assert "grok-hooks-valid" not in loaded
    # And it finds nothing even when a unit test calls it directly.
    assert GrokHooksValidRule().check(context) == []


def test_the_rule_runs_on_a_repository_with_grok_evidence(tmp_path) -> None:
    repo = copy_fixture("grok/project-broken", tmp_path)

    loaded = {rule.rule_id for rule in Linter(RepositoryContext(repo), no_plugins=True).rules}

    assert "grok-hooks-valid" in loaded


# ── The clean fixture ────────────────────────────────────────────


def test_a_well_formed_project_layer_reports_nothing(tmp_path) -> None:
    repo = copy_fixture("grok/project-clean", tmp_path)

    assert check(repo) == []


def test_the_clean_fixture_lints_green(tmp_path) -> None:
    """Including its rules, command, agent and skill, which every content and
    security rule reads."""
    repo = copy_fixture("grok/project-clean", tmp_path)

    assert lint_json(repo)["violations"] == []


# ── The broken fixture: one defect per file ──────────────────────


@pytest.fixture
def broken(tmp_path):
    return check(copy_fixture("grok/project-broken", tmp_path))


#: Every finding the broken fixture makes, as (file, message, severity).
#: Severity is the blast radius the canary matrix measured — a wrong-typed
#: ``timeout`` costs every hook in the file, a missing ``command`` costs one
#: handler — so each case pins its scope through the level it is filed at.
#: The message states the defect and the place, and stops; the rule page
#: carries the rest.
@pytest.mark.parametrize(
    ("filename", "message", "severity"),
    [
        # Whole file: serde refuses the document, so the `Stop` group in the
        # same file never loads either.
        (
            "bad-type.json",
            "Hook SessionStart[0].hooks[0] 'timeout' must be a non-negative integer, got 'ten'",
            Severity.ERROR,
        ),
        # `type` has no default; a handler without one refuses the document.
        ("no-type.json", "Hook PostToolUse[0].hooks[0] is missing 'type'", Severity.ERROR),
        # The event's entries are skipped; the rest of the file loads.
        ("unknown-event.json", "Unknown hook event 'PreToolUseFailure'", Severity.WARNING),
        # Handler scope: siblings in the same group still run.
        (
            "no-command.json",
            "Hook PreCompact[0].hooks[0] is missing 'command'",
            Severity.WARNING,
        ),
        ("no-url.json", "Hook SessionEnd[0].hooks[0] is missing 'url'", Severity.WARNING),
        (
            "unknown-handler-type.json",
            "Hook Notification[0].hooks[0] 'type' must be 'command' or 'http', got 'webhook'",
            Severity.WARNING,
        ),
        # Group scope: the sibling group under the same event still loads.
        (
            "bad-regex.json",
            "Hook PreToolUse[0] 'matcher' 'search_replace|run_terminal_command(' does not "
            "compile: missing ), unterminated subpattern",
            Severity.WARNING,
        ),
        # Advisory: the hook runs, and one thing in it is ignored.
        (
            "env-and-matcher.json",
            "Hook SubagentStart[0].hooks[0] 'env' sets reserved 'GROK_SESSION_ID'",
            Severity.INFO,
        ),
        (
            "env-and-matcher.json",
            "Hook Stop[0] 'matcher' has no effect on Stop",
            Severity.INFO,
        ),
    ],
)
def test_each_defect_is_reported_once(broken, filename, message, severity) -> None:
    """The whole message, not a fragment: a finding states the problem, the
    place and the offending value, and says nothing else."""
    matched = [v for v in broken if v.message == message]

    assert len(matched) == 1, messages(broken)
    assert matched[0].severity == severity
    assert matched[0].file_path.name == filename


def test_the_broken_fixture_reports_nothing_else(broken) -> None:
    """The counts are a noise gate: a new check must land in this fixture."""
    assert len(at(broken, Severity.ERROR)) == 2, messages(broken)
    assert len(at(broken, Severity.WARNING)) == 5, messages(broken)
    assert len(at(broken, Severity.INFO)) == 2, messages(broken)


def test_every_finding_names_a_hooks_file_and_no_line(broken) -> None:
    """JSON has no line numbers, so a fabricated one would be a lie. Grok
    merges a directory of files, so the finding has to name which one."""
    assert broken, "an empty fixture would make both assertions vacuous"
    assert all(v.file_path.parent.name == "hooks" for v in broken)
    assert {v.line for v in broken} == {None}


def test_a_sibling_handler_and_a_sibling_group_are_not_reported(broken) -> None:
    """Handler- and group-scope defects cost exactly what they cost: the
    working handler beside the broken one, and the working group beside the
    uncompilable matcher, are not findings."""
    assert not [m for m in messages(broken) if "PreCompact[0].hooks[1]" in m]
    assert not [m for m in messages(broken) if "PreToolUse[1]" in m]


def test_the_cli_reports_every_finding_against_its_own_file(tmp_path) -> None:
    repo = copy_fixture("grok/project-broken", tmp_path)

    found = violations_for(lint_json(repo, returncode=1), "grok-hooks-valid")

    assert {v["severity"] for v in found} == {"error", "warning", "info"}
    assert all(v["file_path"].startswith(".grok/hooks/") for v in found)
    assert all(v["fixable"] is False for v in found)


# ── Whole-file defects ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("{not json", "Invalid JSON"),
        ("[]", "hooks.json must be a JSON object"),
        ('{"version": 1}', "Missing 'hooks' object"),
        ('{"hooks": []}', "'hooks' must be a JSON object"),
    ],
)
def test_a_file_grok_cannot_load_is_an_error(tmp_path, body, expected) -> None:
    repo = repo_with_hooks(tmp_path, f"unloadable-{abs(hash(body))}", body)

    violations = check(repo)

    assert len(violations) == 1
    assert expected in violations[0].message
    assert violations[0].severity == Severity.ERROR


@pytest.mark.parametrize(
    ("event", "group", "needle"),
    [
        ("Stop", '"not-a-group"', "Hook Stop[0] must be an object"),
        # A group carrying only a matcher: `hooks` has no default, and serde
        # refuses the document without it.
        ("PreToolUse", '{"matcher": "read_file"}', "Hook PreToolUse[0] is missing 'hooks'"),
        (
            "Stop",
            '{"hooks": {"type": "command", "command": "make lint"}}',
            "Hook Stop[0] 'hooks' must be an array of handlers",
        ),
        ("Stop", '{"hooks": ["make lint"]}', "Hook Stop[0].hooks[0] must be an object"),
    ],
)
def test_a_malformed_group_shape_rejects_the_whole_file(tmp_path, event, group, needle) -> None:
    """Each of these costs every other hook in the file, which is what the
    ERROR level says; the message names the shape and the place."""
    repo = repo_with_hooks(
        tmp_path,
        f"group-{abs(hash(group))}",
        '{"hooks": {"' + event + '": [' + group + "]}}",
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].message == needle
    assert violations[0].severity == Severity.ERROR


def test_an_event_whose_value_is_not_an_array_rejects_the_whole_file(tmp_path) -> None:
    repo = repo_with_hooks(
        tmp_path,
        "event-not-array",
        '{"hooks": {"Stop": {"hooks": [{"type": "command", "command": "make lint"}]}}}',
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].message == "Hook event 'Stop' must be an array of matcher groups"
    assert violations[0].severity == Severity.ERROR


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("timeout", "ten", "'timeout' must be a non-negative integer, got 'ten'"),
        ("timeout", 1.5, "'timeout' must be a non-negative integer, got 1.5"),
        ("timeout", -1, "'timeout' must be a non-negative integer, got -1"),
        ("timeout", True, "'timeout' must be a non-negative integer, got True"),
        ("command", 42, "'command' must be a str, got int"),
        ("url", 42, "'url' must be a str, got int"),
        ("env", "MY=1", "'env' must be an object, got str"),
        ("env", {"MY": 1}, "'env' value for 'MY' must be a string, got int"),
    ],
)
def test_a_known_field_of_the_wrong_type_rejects_the_whole_file(
    tmp_path, field, value, expected
) -> None:
    """Refused at parse time, before anything decides which handlers to keep,
    which is what ERROR says here."""
    repo = repo_with_hooks(
        tmp_path,
        f"typed-{field}-{abs(hash(repr(value)))}",
        hooks_doc("Stop", {"type": "command", "command": "make lint", field: value}),
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert expected in violations[0].message
    assert violations[0].severity == Severity.ERROR


def test_a_non_string_type_is_one_finding_not_two(tmp_path) -> None:
    """A list `type` in a set membership test would raise and cost every
    later finding. It is also a known field of the wrong type, which is a
    whole-file verdict rather than a dropped handler."""
    repo = repo_with_hooks(
        tmp_path,
        "unhashable-type",
        '{"hooks": {"Stop": [{"hooks": ['
        '{"type": ["command"], "command": "make lint"},'
        '{"type": "command"}]}]}}',
    )

    violations = check(repo)

    assert len(violations) == 2, messages(violations)
    assert violations[0].message == "Hook Stop[0].hooks[0] 'type' must be a str, got list"
    assert violations[1].message == "Hook Stop[0].hooks[1] is missing 'command'"


@pytest.mark.parametrize("matcher", [["read_file"], {"tool": "read_file"}, 42])
def test_a_non_string_matcher_rejects_the_whole_file(tmp_path, matcher) -> None:
    """An unhashable one must not reach the wildcard set membership test:
    `["x"] in frozenset(...)` raises, and a raising rule reports nothing."""
    repo = repo_with_hooks(
        tmp_path,
        f"matcher-type-{abs(hash(repr(matcher)))}",
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": matcher,
                            "hooks": [{"type": "command", "command": "./audit.sh"}],
                        }
                    ]
                }
            }
        ),
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].message == (
        f"Hook PreToolUse[0] 'matcher' must be a string, got {type(matcher).__name__}"
    )
    assert violations[0].severity == Severity.ERROR


def test_a_large_timeout_is_not_a_defect(tmp_path) -> None:
    """`Stop` and `SubagentStop` default to 600 seconds because gates run test
    suites, so a long one is the documented shape, not a mistake."""
    repo = repo_with_hooks(
        tmp_path,
        "long-timeout",
        hooks_doc("Stop", {"type": "command", "command": "make test", "timeout": 1200}),
    )

    assert check(repo) == []


def test_the_largest_timeout_grok_deserializes_is_accepted(tmp_path) -> None:
    """`timeout` is a Rust `u64`, and JSON has no integer width, so the
    boundary is exact. `18446744073709551615` loads in Grok Build 1.0.13."""
    repo = repo_with_hooks(
        tmp_path,
        "u64-max",
        hooks_doc("Stop", {"type": "command", "command": "make test", "timeout": 2**64 - 1}),
    )

    assert check(repo) == []


def test_one_past_the_u64_ceiling_costs_the_whole_file(tmp_path) -> None:
    """`18446744073709551616` refuses the document, the same as `30.0` — so
    it earns the file-scoped ERROR and its own message, because "must be a
    non-negative integer" would be true of it."""
    repo = repo_with_hooks(
        tmp_path,
        "u64-overflow",
        hooks_doc("Stop", {"type": "command", "command": "make test", "timeout": 2**64}),
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].severity == Severity.ERROR
    assert violations[0].message == (
        "Hook Stop[0].hooks[0] 'timeout' must be at most 18446744073709551615 "
        "(Grok reads it as a 64-bit unsigned integer), got 18446744073709551616"
    )


# ── Bytes Python accepts and Grok's reader does not ──────────────


def test_a_utf8_bom_rejects_the_whole_file(tmp_path) -> None:
    """skillsaw reads with `utf-8-sig`, which strips the mark, so the parsed
    document is valid and every shape check passes. Grok's reader does not
    strip it: `grok inspect --json` loaded zero hooks from this file."""
    repo = write_repo(tmp_path / "bom")
    path = write_hooks(repo, HOOKS_JSON)
    path.write_bytes(codecs.BOM_UTF8 + path.read_bytes())

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].severity == Severity.ERROR
    assert violations[0].message == (
        "hooks.json starts with a UTF-8 byte-order mark; Grok reads none of the file"
    )
    assert violations[0].line is None


def test_a_utf8_bom_costs_every_other_finding_in_the_file(tmp_path) -> None:
    """Grok never parses the document, so a shape finding under the mark
    would be about a file it did not read."""
    repo = write_repo(tmp_path / "bom-and-more")
    path = write_hooks(
        repo,
        hooks_doc("Stop", {"type": "command", "command": "make lint", "timeout": "10"}),
    )
    path.write_bytes(codecs.BOM_UTF8 + path.read_bytes())

    assert [v.message for v in check(repo)] == [
        "hooks.json starts with a UTF-8 byte-order mark; Grok reads none of the file"
    ]


def test_the_same_file_without_the_mark_is_clean(tmp_path) -> None:
    """The mark is the whole defect — the bytes after it are a valid file."""
    repo = repo_with_hooks(tmp_path, "no-bom", HOOKS_JSON)

    assert check(repo) == []


# ── Tokens Python accepts and Grok's parser does not ─────────────


@pytest.mark.parametrize(
    ("name", "field", "token", "path"),
    [
        # An untyped field: nothing in the shape checks would look at it.
        ("unknown-key", '"note": NaN', "NaN", "hooks.Stop[0].hooks[0].note"),
        ("timeout", '"timeout": Infinity', "Infinity", "hooks.Stop[0].hooks[0].timeout"),
        ("negative", '"timeout": -Infinity', "-Infinity", "hooks.Stop[0].hooks[0].timeout"),
    ],
)
def test_a_non_finite_token_rejects_the_whole_file(tmp_path, name, field, token, path) -> None:
    """``json.loads`` accepts ``NaN``/``Infinity``; Grok's parser refuses the
    document, so it runs no hook in the file and skillsaw must say so."""
    repo = repo_with_hooks(
        tmp_path,
        f"non-finite-{name}",
        '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "make lint", '
        + field
        + "}]}]}}",
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].severity == Severity.ERROR
    assert violations[0].message == f"'{token}' at {path} is not valid JSON"
    assert violations[0].line is None


def test_a_non_finite_token_costs_every_other_finding_in_the_file(tmp_path) -> None:
    """The whole document is refused, so a second defect in it is moot — and
    the finding names the first token in document order."""
    repo = repo_with_hooks(
        tmp_path,
        "non-finite-and-more",
        '{"hooks": {"Stop": [{"hooks": ['
        '{"type": "command", "command": "make lint", "note": NaN}]}],'
        '"totallyBogus": [{"hooks": [{"type": "command"}]}]}}',
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert "hooks.Stop[0].hooks[0].note" in violations[0].message


def test_a_finite_float_is_left_to_the_field_type_check(tmp_path) -> None:
    """The scan is about tokens JSON has no spelling for, not about floats:
    ``30.0`` is valid JSON, and ``timeout`` refusing it is a field verdict."""
    repo = repo_with_hooks(
        tmp_path,
        "finite-float",
        hooks_doc("Stop", {"type": "command", "command": "make lint", "timeout": 30.0}),
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert "'timeout' must be a non-negative integer, got 30.0" in violations[0].message


# ── Event names and the alias table ──────────────────────────────


@pytest.mark.parametrize(
    "event",
    [
        # All 15 documented events.
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "PermissionDenied",
        "Stop",
        "StopFailure",
        "StopCancelled",
        "Notification",
        "SubagentStart",
        "SubagentStop",
        "PreCompact",
        "PostCompact",
        # Grok's own documented alias.
        "SubagentEnd",
        # The wire spelling, which the hook itself receives.
        "session_start",
        "user_prompt_submit",
        "post_tool_use_failure",
        "stop_cancelled",
        "subagent_end",
        # camelCase, which covers every event but `userPromptSubmit`.
        "sessionStart",
        "preToolUse",
        "permissionDenied",
        "stopFailure",
        "subagentEnd",
        "postCompact",
        # Cursor's per-operation names, so a shared hooks file still loads.
        "beforeShellExecution",
        "beforeMCPExecution",
        "beforeReadFile",
        "afterShellExecution",
        "afterMCPExecution",
        "afterFileEdit",
        "afterAgentResponse",
        "afterAgentThought",
        "beforeSubmitPrompt",
    ],
)
def test_every_spelling_grok_accepts_is_not_a_finding(tmp_path, event) -> None:
    """Accepting the whole alias table is the correctness requirement: a
    missing entry turns a working hooks file into a false "unknown event"."""
    repo = repo_with_hooks(
        tmp_path,
        f"event-{event}",
        hooks_doc(event, {"type": "command", "command": "./scripts/note.sh"}),
    )

    assert check(repo) == []


@pytest.mark.parametrize(
    "event",
    [
        # The one camelCase spelling Grok does not accept, verified beside
        # the thirteen it does.
        "userPromptSubmit",
        # Neither kebab-case nor all-lowercase is an alias.
        "session-start",
        "sessionstart",
        # Names from other hosts' vocabularies.
        "Setup",
        "PermissionRequest",
        "PostToolBatch",
        "PreToolUseFailure",
    ],
)
def test_a_spelling_grok_skips_is_a_warning(tmp_path, event) -> None:
    repo = repo_with_hooks(
        tmp_path,
        f"unknown-{event}",
        hooks_doc(event, {"type": "command", "command": "./scripts/note.sh"}),
    )

    violation = only(check(repo), "Unknown hook event")

    assert violation.message == f"Unknown hook event '{event}'"
    assert violation.severity == Severity.WARNING


def test_an_unknown_event_is_still_shape_checked(tmp_path) -> None:
    """The entries under it are live configuration if the name is real and
    this release has simply not heard of it."""
    repo = repo_with_hooks(
        tmp_path, "unknown-shape", hooks_doc("PreSomethingNew", {"type": "command"})
    )

    violations = check(repo)

    assert len(violations) == 2, messages(violations)
    assert only(violations, "Unknown hook event").severity == Severity.WARNING
    assert only(violations, "is missing 'command'").severity == Severity.WARNING


# ── Matchers ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "matcher",
    [
        # Grok special-cases `*` as a catch-all; Rust's regex engine would
        # reject it as a dangling repeat, and so does Python's `re`.
        "*",
        # An empty matcher means the same thing. It compiles fine in Python,
        # so this case guards the intent rather than the exception.
        "",
        # Rust's regex crate compiles Unicode classes and class-set
        # operators; Python's `re` raises on both, and reporting a working
        # matcher as broken is the false positive worth avoiding.
        r"\p{L}+",
        r"\pL",
        "[a-z&&[^aeiou]]",
        r"[\w--\d]",
        # Rust's named capture group. Python spells it `(?P<tool>...)` and
        # raises "unknown extension ?<t" on this one, so the rewrite has to
        # cover it — and must not swallow `(?<=` / `(?<!`, which are
        # look-behind and reported above.
        "(?<tool>Bash|Write)",
    ],
)
def test_the_matchers_python_cannot_compile_but_grok_can(tmp_path, matcher) -> None:
    """`re` is not Grok's engine, so a pattern only Rust accepts is not a defect."""
    repo = repo_with_hooks(
        tmp_path,
        f"matcher-{abs(hash(matcher))}",
        hooks_doc("PreToolUse", {"type": "command", "command": "./audit.sh"}, matcher=matcher),
    )

    assert check(repo) == []


@pytest.mark.parametrize(
    "matcher",
    [
        # A Rust-only atom is rewritten to its nearest Python spelling rather
        # than waiving the pattern: what is left here is an unclosed group
        # and an unclosed character class, which Rust rejects too.
        r"(\pL",
        r"[\w--\d",
    ],
)
def test_a_rust_only_atom_does_not_waive_the_rest_of_the_pattern(tmp_path, matcher) -> None:
    repo = repo_with_hooks(
        tmp_path,
        f"rust-atom-{abs(hash(matcher))}",
        hooks_doc("PreToolUse", {"type": "command", "command": "./audit.sh"}, matcher=matcher),
    )

    assert only(check(repo), "does not compile").severity == Severity.WARNING


@pytest.mark.parametrize(
    ("matcher", "detail"),
    [
        (r"(?<=x)y", "Rust's regex has no look-around"),
        ("(?=Write)Write", "Rust's regex has no look-around"),
        (r"(a)\1", "Rust's regex has no backreferences"),
        ("(?P<n>a)(?P=n)", "Rust's regex has no backreferences"),
    ],
)
def test_a_construct_python_accepts_and_rust_refuses_is_named(tmp_path, matcher, detail) -> None:
    """Compiling with `re` cannot see these. Python accepts look-around and
    backreferences; Rust, a finite-automaton engine, has neither, and Grok
    drops the matcher group without a word. Verified against Grok Build
    1.0.13: `(?<=x)y` and `(a)\\1` each lost their group."""
    repo = repo_with_hooks(
        tmp_path,
        f"unsupported-{abs(hash(matcher))}",
        hooks_doc("PreToolUse", {"type": "command", "command": "./audit.sh"}, matcher=matcher),
    )

    violations = check(repo)

    assert len(violations) == 1
    assert violations[0].severity == Severity.WARNING
    assert violations[0].message.endswith(f"does not compile: {detail}")


@pytest.mark.parametrize("matcher", [r"\(?=", "[(?=]"])
def test_a_look_around_run_that_is_only_literal_text_is_not_reported(tmp_path, matcher) -> None:
    """`\\(?=` is an optional literal paren and `[(?=]` is a character class:
    both dialects read the run as text, so naming a construct here would call
    a working matcher broken."""
    repo = repo_with_hooks(
        tmp_path,
        f"literal-{abs(hash(matcher))}",
        hooks_doc("PreToolUse", {"type": "command", "command": "./audit.sh"}, matcher=matcher),
    )

    assert check(repo) == []


def test_an_oversized_matcher_is_never_scanned(tmp_path) -> None:
    """`.grok/hooks/*.json` is repository-controlled, so the compile check is
    capped rather than handed a matcher of any size. Past the cap the rule
    reports nothing about it — Grok has no length limit, so length is not a
    defect — and finishes the rest of the file as usual."""
    repo = write_repo(tmp_path / "oversized")
    matcher = "\\p{" * 34_000
    assert len(matcher) > 100_000
    write_hooks(
        repo,
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": matcher,
                            "hooks": [{"type": "command", "command": "./audit.sh"}],
                        }
                    ],
                    "Stop": [{"hooks": [{"type": "command"}]}],
                }
            }
        ),
    )

    started = time.perf_counter()
    violations = check(repo)
    elapsed = time.perf_counter() - started

    # Generous enough not to flake on a loaded CI runner, and still orders of
    # magnitude below the quadratic scan it guards against.
    assert elapsed < 5.0, f"took {elapsed:.1f}s"
    assert [v for v in violations if "does not compile" in v.message] == []
    assert only(violations, "is missing 'command'")


def test_a_matcher_on_an_event_that_ignores_it_is_advisory(tmp_path) -> None:
    """`Stop` and `UserPromptSubmit` always fire, so Grok never even compiles
    the pattern — an uncompilable one there costs nothing, which is why the
    finding is INFO and the syntax check does not run."""
    repo = repo_with_hooks(
        tmp_path,
        "stop-matcher",
        hooks_doc("Stop", {"type": "command", "command": "make lint"}, matcher="end_turn("),
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].message == "Hook Stop[0] 'matcher' has no effect on Stop"
    assert violations[0].severity == Severity.INFO


@pytest.mark.parametrize("matcher", ["", "*"])
def test_a_catch_all_matcher_on_an_ignored_event_is_not_a_finding(tmp_path, matcher) -> None:
    """ "Everything" is what an omitted matcher already means, so saying it
    has no effect on an event that always fires is a finding with no defect."""
    repo = repo_with_hooks(
        tmp_path,
        f"stop-wildcard-{abs(hash(matcher))}",
        hooks_doc("Stop", {"type": "command", "command": "make lint"}, matcher=matcher),
    )

    assert check(repo) == []


def test_a_malformed_env_is_one_finding_not_two(tmp_path) -> None:
    """A non-string value refuses the whole document, so nothing is stripped
    and the reserved-name advisory would be describing a hook that never
    runs."""
    repo = repo_with_hooks(
        tmp_path,
        "malformed-env",
        hooks_doc(
            "SessionStart",
            {
                "type": "command",
                "command": "./bootstrap.sh",
                "env": {"GROK_SESSION_ID": 1},
            },
        ),
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert (
        violations[0].message == "Hook SessionStart[0].hooks[0] 'env' value for 'GROK_SESSION_ID' "
        "must be a string, got int"
    )
    assert violations[0].severity == Severity.ERROR


def test_the_ignored_matcher_advice_follows_the_alias_table(tmp_path) -> None:
    """`stop` and `beforeSubmitPrompt` are the same two events under other
    names, so the advice has to normalize before it decides."""
    repo = repo_with_hooks(
        tmp_path,
        "aliased-matcher",
        json.dumps(
            {
                "hooks": {
                    "stop": [
                        {
                            "matcher": "end_turn",
                            "hooks": [{"type": "command", "command": "make lint"}],
                        }
                    ],
                    "beforeSubmitPrompt": [
                        {
                            "matcher": "anything",
                            "hooks": [{"type": "command", "command": "./check.sh"}],
                        }
                    ],
                }
            }
        ),
    )

    violations = check(repo)

    assert sorted(messages(violations)) == [
        "Hook beforeSubmitPrompt[0] 'matcher' has no effect on beforeSubmitPrompt",
        "Hook stop[0] 'matcher' has no effect on stop",
    ]
    assert {v.severity for v in violations} == {Severity.INFO}


# ── Handlers ─────────────────────────────────────────────────────


def test_a_handler_key_grok_does_not_know_is_not_a_finding(tmp_path) -> None:
    """Grok tolerates unknown keys on a handler, on a matcher group and at
    the top level, so reporting one would be a finding with no defect."""
    repo = repo_with_hooks(
        tmp_path,
        "unknown-keys",
        json.dumps(
            {
                "$schema": "https://grok.example/hooks.json",
                "version": 2,
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "end",
                            "description": "left over from a Claude Code file",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "make lint",
                                    "statusMessage": "Linting",
                                }
                            ],
                        }
                    ]
                },
            }
        ),
    )

    # `matcher` on `Stop` is the one advisory the document earns.
    assert messages(check(repo)) == ["Hook Stop[0] 'matcher' has no effect on Stop"]


def test_an_http_handler_needs_a_url_and_not_a_command(tmp_path) -> None:
    repo = repo_with_hooks(
        tmp_path,
        "http-handler",
        hooks_doc(
            "SessionEnd",
            {"type": "http", "url": "https://hooks.example.test/e", "timeout": 10},
        ),
    )

    assert check(repo) == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('{"hooks": {}}', "'hooks' is empty"),
        ('{"hooks": {"Stop": []}}', "Hook event 'Stop' has an empty array"),
        (
            '{"hooks": {"Stop": [{"hooks": []}]}}',
            "Hook Stop[0] has an empty 'hooks' array",
        ),
    ],
)
def test_a_valid_file_that_configures_nothing_is_a_warning(tmp_path, body, expected) -> None:
    repo = repo_with_hooks(tmp_path, f"empty-{abs(hash(body))}", body)

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].message == expected
    assert violations[0].severity == Severity.WARNING


def test_reserved_env_names_are_reported_and_the_rest_are_not(tmp_path) -> None:
    """The runner injects its own value for each of these whatever the file
    says; a project variable beside them is untouched."""
    repo = repo_with_hooks(
        tmp_path,
        "reserved-env",
        hooks_doc(
            "SessionStart",
            {
                "type": "command",
                "command": "./bootstrap.sh",
                "env": {
                    "GROK_WORKSPACE_ROOT": "/tmp/elsewhere",
                    "CLAUDE_PROJECT_DIR": "/tmp/elsewhere",
                    "WAYPOINT_LOG": "debug",
                },
            },
        ),
    )

    violations = check(repo)

    assert sorted(messages(violations)) == [
        "Hook SessionStart[0].hooks[0] 'env' sets reserved 'CLAUDE_PROJECT_DIR'",
        "Hook SessionStart[0].hooks[0] 'env' sets reserved 'GROK_WORKSPACE_ROOT'",
    ]
    assert {v.severity for v in violations} == {Severity.INFO}


# ── extra-events ─────────────────────────────────────────────────


def test_extra_events_accepts_an_event_newer_than_this_release(tmp_path) -> None:
    repo = copy_fixture("grok/project-broken", tmp_path)

    silenced = check(repo, {"extra-events": ["PreToolUseFailure"]})

    assert not [m for m in messages(silenced) if "PreToolUseFailure" in m]
    # Only the named event is accepted; every other verdict is unchanged.
    assert only(silenced, "is missing 'url'")


def test_an_accepted_event_keeps_its_entries_shape_checked(tmp_path) -> None:
    repo = repo_with_hooks(
        tmp_path, "future-event", hooks_doc("PreSomethingNew", {"type": "command"})
    )

    violations = check(repo, {"extra-events": ["PreSomethingNew"]})

    assert len(violations) == 1
    assert "is missing 'command'" in violations[0].message


def test_a_wrong_shaped_list_option_costs_no_other_finding(tmp_path) -> None:
    """The declared type is not enforced at load, so 42 must not raise here."""
    repo = copy_fixture("grok/project-broken", tmp_path)

    violations = check(repo, {"extra-events": 42})

    assert only(violations, "Unknown hook event 'PreToolUseFailure'")
    assert len(at(violations, Severity.ERROR)) == 2, messages(violations)


def test_extra_events_is_configurable_through_a_config_file(tmp_path) -> None:
    repo = copy_fixture("grok/project-broken", tmp_path)
    (repo / ".skillsaw.yaml").write_text(
        'version: "99.0.0"\n'
        "rules:\n"
        "  grok-hooks-valid:\n"
        "    extra-events:\n"
        "      - PreToolUseFailure\n"
    )

    found = violations_for(lint_json(repo, returncode=1), "grok-hooks-valid")

    assert not [v for v in found if "PreToolUseFailure" in v["message"]]
    assert [v for v in found if "must be a non-negative integer" in v["message"]]


# ── Configured severity ───────────────────────────────────────────


def test_a_configured_severity_moves_the_file_scoped_findings_only(tmp_path) -> None:
    """The ERRORs follow the user's override; the scope-derived WARNING and
    INFO are the rule's verdict on blast radius, not its severity, and stay
    put whatever the user configures."""
    repo = copy_fixture("grok/project-broken", tmp_path)
    (repo / ".skillsaw.yaml").write_text(
        'version: "99.0.0"\nrules:\n  grok-hooks-valid:\n    severity: warning\n'
    )

    found = violations_for(lint_json(repo, returncode=1), "grok-hooks-valid")

    # The two file-scope ERRORs join the five already-WARNING findings; the
    # two hardcoded INFO findings are untouched.
    assert {v["severity"] for v in found} == {"warning", "info"}
    assert len([v for v in found if v["severity"] == "info"]) == 2
