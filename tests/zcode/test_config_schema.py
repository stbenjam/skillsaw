""".zcode/config.json parsing and per-server schema checks."""

from __future__ import annotations


from ._helpers import lint, messages, rule_ids, write_json


def test_non_finite_tokens_make_the_project_config_invalid(tmp_path):
    config = tmp_path / ".zcode" / "config.json"
    config.parent.mkdir()
    config.write_text('{"hooks": {"timeoutMs": Infinity}}\n')
    (finding,) = messages(lint(tmp_path), "zcode-config-valid")
    assert finding.startswith("Invalid JSON")


def test_huge_integer_timeout_does_not_crash_the_rule(tmp_path):
    config = tmp_path / ".zcode" / "config.json"
    config.parent.mkdir()
    config.write_text('{"hooks": {"timeoutMs": 1' + "0" * 400 + ', "enabled": "on"}}\n')
    report = lint(tmp_path)
    assert "rule-execution-error" not in rule_ids(report)
    assert any("'hooks.enabled'" in m for m in messages(report, "zcode-config-valid"))


def test_accepted_server_fields_are_type_checked(tmp_path):
    write_json(
        tmp_path / ".zcode" / "config.json",
        {
            "mcp": {
                "servers": {
                    "flag": {"command": "serve", "enabled": "no"},
                    "auth": {"url": "https://example.com/mcp", "oauth": "token"},
                    "grant": {
                        "url": "https://example.com/mcp",
                        "oauth": {"type": "client_credentials", "clientId": "acme"},
                    },
                }
            }
        },
    )
    found = messages(lint(tmp_path), "zcode-config-valid")
    assert any("'flag'" in m and "'enabled' must be a boolean" in m for m in found)
    assert any("'auth'" in m and "'oauth' must be an object" in m for m in found)
    assert any("'grant'" in m and "'oauth.clientSecret' is required" in m for m in found)


def test_matcher_group_keys_oauth_grants_and_shadowed_aliases(tmp_path):
    write_json(
        tmp_path / ".zcode" / "config.json",
        {
            "hooks": {
                "events": {
                    "Stop": [{"match": "Bash", "hooks": [{"type": "command", "command": "make"}]}]
                }
            },
            "mcp": {
                "servers": {
                    "grant": {
                        "url": "https://e.com/mcp",
                        "oauth": {
                            "type": "client_credentials",
                            "clientId": "a",
                            "clientSecret": "${SECRET}",
                            "redirectPath": "/cb",
                        },
                    },
                    "imported": {"command": "db-mcp", "env": {"A": "b"}, "environment": "old"},
                    "badtype": {"type": "https://ops:t0ken-value@e.com", "url": "x"},
                }
            },
        },
    )
    found = messages(lint(tmp_path), "zcode-config-valid")
    assert any("unknown key(s) 'match'" in m for m in found)
    assert any("'grant'" in m and "redirectPath" in m for m in found)
    assert not any("'imported'" in m for m in found)
    assert any("'badtype'" in m for m in found)
    assert not any("t0ken-value" in m for m in found)


def test_environment_on_a_remote_server_is_rejected_as_env(tmp_path):
    """ZCode renames ``environment`` to ``env``, which a remote server rejects."""
    write_json(
        tmp_path / ".zcode" / "config.json",
        {"mcp": {"servers": {"docs": {"url": "https://e.com/mcp", "environment": {"A": "b"}}}}},
    )
    found = messages(lint(tmp_path), "zcode-config-valid")
    assert any("'docs'" in m and "env" in m for m in found)


def test_empty_oauth_fields_and_explicit_nulls(tmp_path):
    write_json(
        tmp_path / ".zcode" / "config.json",
        {
            "mcp": {
                "servers": {
                    "grant": {
                        "url": "https://e.com/mcp",
                        "oauth": {"type": "authorization_code", "clientName": ""},
                    }
                }
            }
        },
    )
    assert any(
        "'oauth.clientName' must be a non-empty string" in m
        for m in messages(lint(tmp_path), "zcode-config-valid")
    )
    write_json(tmp_path / ".zcode" / "config.json", {"mcp": None})
    assert any(
        "'mcp' must be an object" in m for m in messages(lint(tmp_path), "zcode-config-valid")
    )
    write_json(tmp_path / ".zcode" / "config.json", {"mcp": {"servers": None}})
    assert any(
        "'mcp.servers' must be an object" in m
        for m in messages(lint(tmp_path), "zcode-config-valid")
    )
