"""Native-derived hook decoder controls; all command strings remain inert."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks.json_config import AntigravityHooksBlock
from skillsaw.rules.builtin.antigravity.hooks_valid import AntigravityHooksValidRule
from ._helpers import repo_with_hooks, run_rule


def _check(tmp_path, body):
    repo = repo_with_hooks(tmp_path, "hooks", body)
    return run_rule(AntigravityHooksValidRule, repo), AntigravityHooksBlock(
        path=repo / ".agents/hooks.json"
    )


@pytest.mark.parametrize(
    "key,valid,invalid",
    [
        ("Type", "command", 42),
        ("Command", "/audit/not-an-executable", 42),
        ("Prompt", "", 42),
        ("Model", "", 42),
        ("Timeout", 5, "5"),
    ],
)
def test_handler_field_case_keeps_its_type_contract(tmp_path, key, valid, invalid):
    for label, value in (("valid", valid), ("invalid", invalid)):
        fields = {"command": "/audit/not-an-executable", key: value}
        findings, block = _check(tmp_path / label, json.dumps({"review": {"Stop": [fields]}}))
        assert len(findings) == (0 if label == "valid" else 1)
        if findings:
            assert f"'{key}' must be" in findings[0].message
            assert "loads no hook from this file" in findings[0].message
        else:
            assert len(block.events["Stop"]) == 1


@pytest.mark.parametrize(
    "fields,valid",
    [
        ('"Type":"prompt","type":null,"prompt":"Check formatting."', True),
        ('"type":"command","Type":"prompt","prompt":"Check formatting."', True),
        ('"type":"prompt","Type":"command","prompt":"Check formatting."', False),
        ('"type":"unknown","Type":"command","command":"audit"', True),
        ('"type":42,"Type":"command","command":"audit"', False),
        ('"Command":42,"command":"audit"', False),
        ('"command":"audit","prompt":"Check formatting.","PROMPT":null', False),
        ('"command":"audit","prompt":"Check formatting.","PROMPT":""', True),
        ('"command":"audit","model":"example-model","MODEL":null', False),
    ],
)
def test_duplicate_scalars_separate_decode_types_from_final_semantics(tmp_path, fields, valid):
    findings, _ = _check(tmp_path, '{"review":{"Stop":[{' + fields + "}]}}")
    assert len(findings) == (0 if valid else 1)
    if findings:
        assert "loads no hook from this file" in findings[0].message


@pytest.mark.parametrize(
    "body,needle",
    [
        ('{"review":{"Stop":42,"STOP":[]}}', "event's value must be an array"),
        ('{"review":{"Stop":[{"Command":42}],"STOP":[]}}', "'Command' must be a string"),
        ('{"review":42,"review":{}}', "named hook must be a JSON object"),
        ('{"review":{"Stop":[{"command":42}]},"review":{}}', "'command' must be a string"),
        ('{"review":{"PreToolUse":[{"Hooks":42,"hooks":[]}]}}', "'Hooks' must be an array"),
        (
            '{"review":{"PreToolUse":[{"Matcher":42,"matcher":"read_file","hooks":[]}]}}',
            "'Matcher' must be a string",
        ),
    ],
)
def test_errors_in_replaced_objects_still_reject_the_file(tmp_path, body, needle):
    findings, _ = _check(tmp_path, body)
    assert len(findings) == 1
    assert needle in findings[0].message


def test_replaced_unknown_fields_do_not_leave_stale_advisories(tmp_path):
    findings, block = _check(
        tmp_path, '{"review":{"Stop":[{"metadata":42}]},"review":{"Stop":[{"Command":"audit"}]}}'
    )
    assert findings == []
    assert block.events["Stop"][0].handlers[0].command == "audit"


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_json_number_tokens_still_reject_the_file(tmp_path, token):
    findings, _ = _check(
        tmp_path, '{"review":{"Stop":[{"command":"audit","metadata":' + token + "}]}}"
    )
    assert len(findings) == 1
    assert "does not parse" in findings[0].message


def test_hook_names_keep_case_and_known_events_use_go_simple_fold(tmp_path):
    body = '{"Review":{"ſtop":[{"Command":"first"}]},"review":{"Stop":[{"Command":"second"}]}}'
    findings, block = _check(tmp_path, body)
    assert findings == []
    assert [c.handlers[0].command for c in block.events["Stop"]] == ["first", "second"]


def test_full_unicode_expansions_do_not_turn_unknown_events_into_known_ones(tmp_path):
    findings, block = _check(tmp_path, '{"review":{"SeßionStart":[{"Command":"audit"}]}}')
    assert len(findings) == 1
    assert "not one Antigravity dispatches" in findings[0].message
    assert list(block.events) == ["SeßionStart"]


def test_matcher_null_keeps_prior_string_for_shared_extraction(tmp_path):
    findings, block = _check(
        tmp_path,
        '{"review":{"PreToolUse":[{"Matcher":"read_file","matcher":null,"Hooks":[{"Command":"audit"}]}]}}',
    )
    assert findings == []
    assert block.events["PreToolUse"][0].matcher == "read_file"
