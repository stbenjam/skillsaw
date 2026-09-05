"""Antigravity 1.1.26 MCP metadata-decoder controls; no servers are executed."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks.json_config import AntigravityMcpBlock
from skillsaw.rules.builtin.antigravity.mcp_valid import AntigravityMcpValidRule
from ._helpers import repo_with_mcp, run_rule


@pytest.mark.parametrize(
    "key,good,bad",
    [
        ("Command", "audit", 42),
        ("URL", "https://example.invalid/mcp", 42),
        ("serverURL", "https://example.invalid/mcp", 42),
        ("CWD", "/audit", []),
        ("ARGS", ["--read-only", None], "--read-only"),
        ("ENV", {"PORT": None}, {"PORT": 42}),
        ("Headers", {"X-Count": None}, {"X-Count": False}),
        ("OAuth", {"ClientId": None, "extra": 42}, {"ClientId": 42}),
        ("Disabled", True, "true"),
        ("DisabledTools", ["write", None], "write"),
        ("AuthProviderType", "google_credentials", "unsupported"),
        ("ſerverUrl", "https://example.invalid/mcp", 42),
    ],
)
def test_recognized_field_spelling_keeps_its_type_contract(tmp_path, key, good, bad):
    for label, value in (("valid", good), ("invalid", bad)):
        body = json.dumps({"mcpServers": {"probe": {key: value}}})
        repo = repo_with_mcp(tmp_path, label, body)
        findings = run_rule(AntigravityMcpValidRule, repo)
        if label == "valid":
            assert findings == []
        else:
            assert len(findings) == 1
            assert key in findings[0].message
            assert "drops the server silently" in findings[0].message


@pytest.mark.parametrize("key", ["headers", "oauth", "disabled"])
@pytest.mark.parametrize("value", [None, 42, "value", [], {}])
def test_new_field_shapes_match_their_go_types(tmp_path, key, value):
    repo = repo_with_mcp(tmp_path, "shape", json.dumps({"mcpServers": {"probe": {key: value}}}))
    findings = run_rule(AntigravityMcpValidRule, repo)
    accepted = value is None or (key != "disabled" and isinstance(value, dict))
    assert len(findings) == (0 if accepted else 1)
    if findings:
        assert f"'{key}' must be" in findings[0].message


@pytest.mark.parametrize(
    "body,expected",
    [
        ('{"Command":"first","command":"last"}', "last"),
        ('{"command":"first","Command":"last"}', "last"),
        ('{"Command":"first","COMMAND":null}', None),
    ],
)
def test_case_collisions_keep_encounter_order(tmp_path, body, expected):
    repo = repo_with_mcp(tmp_path, "ordered", '{"mcpServers":{"probe":' + body + "}}")
    block = AntigravityMcpBlock(path=repo / ".agents/mcp_config.json")
    assert block.servers[0].name == "probe"
    assert block.servers[0].command == expected
    assert run_rule(AntigravityMcpValidRule, repo) == []


@pytest.mark.parametrize("field", ["env", "headers", "oauth"])
@pytest.mark.parametrize("clear", [False, True])
def test_mixed_case_maps_merge_and_null_clears(tmp_path, field, clear):
    second = "null" if clear else '{"MODE":"read"}'
    body = (
        '{"mcpServers":{"probe":{"'
        + field
        + '":{"Mode":"ferry"},"'
        + field.upper()
        + '":'
        + second
        + "}}}"
    )
    repo = repo_with_mcp(tmp_path, "maps", body)
    block = AntigravityMcpBlock(path=repo / ".agents/mcp_config.json")
    expected = None if clear else {"Mode": "ferry", "MODE": "read"}
    assert block.raw_data["mcpServers"]["probe"][field] == expected
    assert run_rule(AntigravityMcpValidRule, repo) == []


@pytest.mark.parametrize(
    "fields,needle",
    [
        ('"Command":42,"command":"audit"', "'Command' must be a string"),
        ('"Args":42,"args":[]', "'Args' must be an array"),
        ('"Env":{"PORT":42},"env":{"PORT":"80"}', "every 'Env' value"),
        ('"env":{"PORT":42,"PORT":"80"}', "every 'env' value"),
        ('"OAuth":{"ClientId":42,"clientId":"audit"}', "'OAuth.ClientId'"),
        ('"Disabled":"true","disabled":true', "'Disabled' must be a boolean"),
    ],
)
def test_later_fields_do_not_erase_an_earlier_type_error(tmp_path, fields, needle):
    repo = repo_with_mcp(tmp_path, "duplicate", '{"mcpServers":{"probe":{' + fields + "}}}")
    findings = run_rule(AntigravityMcpValidRule, repo)
    assert len(findings) == 1
    assert needle in findings[0].message
    assert "drops the server silently" in findings[0].message


def test_repeated_invalid_field_is_one_defect(tmp_path):
    repo = repo_with_mcp(
        tmp_path, "invalid", '{"mcpServers":{"probe":{"Command":42,"command":43}}}'
    )
    findings = run_rule(AntigravityMcpValidRule, repo)
    assert len(findings) == 1
    assert "'Command' must be a string" in findings[0].message


@pytest.mark.parametrize(
    "fields",
    [
        '"dißabled":"true"',
        '"clientId":42,"clientSecret":[]',
        '"OAuth":{"extra":42,"metadata":{"revision":2}}',
        '"timeout":1e400',
    ],
)
def test_unknown_fields_stay_outside_the_typed_contract(tmp_path, fields):
    repo = repo_with_mcp(tmp_path, "unknown", '{"mcpServers":{"probe":{' + fields + "}}}")
    assert run_rule(AntigravityMcpValidRule, repo) == []


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_json_numeric_tokens_still_fail(tmp_path, token):
    repo = repo_with_mcp(tmp_path, "numeric", '{"mcpServers":{"probe":{"timeout":' + token + "}}}")
    findings = run_rule(AntigravityMcpValidRule, repo)
    assert len(findings) == 1
    assert "Invalid JSON" in findings[0].message
    assert "exits 1" in findings[0].message


@pytest.mark.parametrize(
    "key,first",
    [
        ("command", "audit"),
        ("serverUrl", "https://example.invalid/mcp"),
        ("args", ["--read-only"]),
        ("disabled", True),
        ("authProviderType", "google_credentials"),
    ],
)
def test_null_clears_prior_scalar_and_slice_values(tmp_path, key, first):
    fields = json.dumps(key) + ":" + json.dumps(first) + "," + json.dumps(key.upper()) + ":null"
    repo = repo_with_mcp(tmp_path, "null", '{"mcpServers":{"probe":{' + fields + "}}}")
    block = AntigravityMcpBlock(path=repo / ".agents/mcp_config.json")
    assert block.raw_data["mcpServers"]["probe"][key] is None
    assert run_rule(AntigravityMcpValidRule, repo) == []
    if key == "command":
        assert block.servers[0].command is None


@pytest.mark.parametrize(
    "fields",
    [
        '"oauth":{"clientId":"audit","CLIENTID":null,"clientSecret":"fixture","CLIENTSECRET":null}',
        '"oauth":{"clientId":"audit","clientSecret":"fixture"},"OAUTH":{"CLIENTID":null,"CLIENTSECRET":null}',
    ],
)
def test_null_oauth_members_clear_prior_credentials(tmp_path, fields):
    repo = repo_with_mcp(tmp_path, "null-oauth", '{"mcpServers":{"probe":{' + fields + "}}}")
    block = AntigravityMcpBlock(path=repo / ".agents/mcp_config.json")
    assert block.servers[0].oauth == {"clientId": None, "clientSecret": None}
    assert run_rule(AntigravityMcpValidRule, repo) == []


def test_oauth_case_merge_keeps_unreplaced_credentials(tmp_path):
    fields = '"oauth":{"clientId":"audit","clientSecret":"fixture"},"OAUTH":{"CLIENTID":"new"}'
    repo = repo_with_mcp(tmp_path, "oauth", '{"mcpServers":{"probe":{' + fields + "}}}")
    block = AntigravityMcpBlock(path=repo / ".agents/mcp_config.json")
    assert block.servers[0].oauth == {"clientId": "new", "clientSecret": "fixture"}
    assert run_rule(AntigravityMcpValidRule, repo) == []
