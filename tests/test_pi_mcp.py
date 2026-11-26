"""Pi MCP discovery and CLI regressions from the released 1.5.0 contract."""

import json

import pytest

from skillsaw.blocks.json_config import McpBlock
from skillsaw.blocks.pi import PiMcpBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.pi.mcp_valid import PiMcpValidRule, _problem
from skillsaw.utils import invalidate_read_caches
from tests.cli_runner import run_cli
from tests.test_pi import copy_fixture


def lint(root, *extra):
    result = run_cli(["lint", str(root), "--format", "json", *extra])
    return result, json.loads(result.stdout)["violations"]


def test_mcp_only_project_detected_and_attached_under_forced_type(tmp_path):
    root = copy_fixture("mcp-valid", tmp_path)
    nested = root / "packages" / "service"
    nested.mkdir(parents=True)
    (root / ".pi").rename(nested / ".pi")
    for forced in (None, {RepositoryType.DOT_CLAUDE}):
        context = RepositoryContext(root, repo_types=forced)
        if forced is None:
            assert context.repo_type is RepositoryType.PI
        blocks = context.lint_tree.find(McpBlock)
        assert len(blocks) == 1
        assert isinstance(blocks[0], PiMcpBlock)
        assert blocks[0].server_names == {"workspace", "docs"}
        assert not context.lint_tree_errors


def test_valid_pi_mcp_cli_and_opt_in_shape_checks(tmp_path):
    root = copy_fixture("mcp-valid", tmp_path)
    result, findings = lint(root, "--rule", "pi-mcp-valid", "--rule", "mcp-valid-json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert findings == []
    assert PiMcpValidRule.default_enabled is False


def test_invalid_pi_mcp_reports_once_per_defect(tmp_path):
    root = copy_fixture("mcp-invalid", tmp_path)
    _, findings = lint(root, "--rule", "pi-mcp-valid", "--rule", "mcp-valid-json")
    assert len(findings) == 7
    assert {f["rule_id"] for f in findings} == {"pi-mcp-valid"}
    assert {f["severity"] for f in findings} == {"warning"}
    assert all("line" not in f or f["line"] is None for f in findings)
    assert any("conflicts with 'dev-tools'" in f["message"] for f in findings)
    assert any("global mcp.json" in f["message"] for f in findings)


@pytest.mark.parametrize(
    "extra",
    [
        (),
        ("--skip-rule", "pi-mcp-valid"),
        ("--type", "dot-claude"),
    ],
)
def test_shared_security_survives_opt_in_shape_gating(tmp_path, extra):
    root = copy_fixture("mcp-valid", tmp_path)
    path = root / ".pi/mcp.json"
    data = json.loads(path.read_text())
    token = "ghp_" + "A1b2" * 10
    data["mcpServers"]["docs"]["oauth"]["clientSecret"] = token
    data["mcpServers"]["docs"]["headers"]["Authorization"] = "!echo " + token
    path.write_text(json.dumps(data))
    _, all_findings = lint(root, *extra)
    findings = [f for f in all_findings if f["rule_id"] == "mcp-valid-json"]
    assert len(findings) == 2
    assert all(f["rule_id"] == "mcp-valid-json" for f in findings)
    assert any("clientSecret" in f["message"] for f in findings)
    assert all(token not in f["message"] for f in findings)
    _, policy = lint(root, "--rule", "mcp-prohibited")
    assert len(policy) == 1
    assert policy[0]["rule_id"] == "mcp-prohibited"


def test_syntax_owned_once_by_shared_rule_and_duplicate_keys_last_win(tmp_path):
    root = copy_fixture("mcp-valid", tmp_path)
    path = root / ".pi/mcp.json"
    path.write_text('{"mcpServers": {}, "mcpServers": {"docs": {"command": ""}}}')
    _, findings = lint(root, "--rule", "pi-mcp-valid", "--rule", "mcp-valid-json")
    assert findings == []
    path.write_text('{"mcpServers": NaN}')
    _, findings = lint(root, "--rule", "pi-mcp-valid", "--rule", "mcp-valid-json")
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "mcp-valid-json"


def test_missing_wrapper_is_inert_and_severity_override_respected(tmp_path):
    root = copy_fixture("mcp-valid", tmp_path)
    path = root / ".pi/mcp.json"
    path.write_text('{"docs": {"command": "uvx"}, "autoEnableCodemode": false}')
    _, findings = lint(root, "--rule", "pi-mcp-valid", "--rule", "mcp-valid-json")
    assert findings == []
    path.write_text('{"mcpServers": null}')
    invalidate_read_caches()
    findings = PiMcpValidRule({"severity": "error"}).check(RepositoryContext(root))
    assert len(findings) == 1
    assert findings[0].severity.value == "error"


@pytest.mark.parametrize(
    "config,part",
    [
        (None, "object"),
        ({"command": "uvx", "enabled": None}, "enabled"),
        ({"command": "uvx", "timeout": True}, "timeout"),
        ({"command": "uvx", "timeout": 0}, "timeout"),
        ({"command": "uvx", "description": []}, "description"),
        ({"command": "uvx", "type": None}, "declare command"),
        ({"command": "uvx", "env": {"COUNT": 1}}, "env"),
        ({"command": "uvx", "cwd": False}, "cwd"),
        ({"url": "https://example.com", "headers": []}, "headers"),
        ({"url": "https://example.com", "oauth": None}, "oauth"),
        ({"url": "https://example.com", "oauth": {"clientSecret": 42}}, "clientSecret"),
        ({"url": "https://example.com", "oauth": {"clientName": ""}}, "clientName"),
        ({"url": "https://example.com", "oauth": {"callbackPort": 65536}}, "callbackPort"),
        ({"url": "https://example.com", "oauth": {"callbackPort": 1.5}}, "callbackPort"),
    ],
)
def test_rejected_types(config, part):
    assert part in _problem(config)


@pytest.mark.parametrize(
    "config",
    [
        {"command": ""},
        {"command": "uvx", "timeout": 0.5, "unknown": True},
        {"command": "uvx", "url": 42, "oauth": None},
        {"type": "stdio", "command": "uvx", "url": "https://example.com", "headers": 42},
        {"url": "https://example.com", "command": 42, "args": None, "env": 42},
        {"url": "https://example.com", "oauth": {"callbackPort": 1234.0}},
    ],
)
def test_transport_precedence_and_tolerated_values(config):
    assert _problem(config) is None


@pytest.mark.parametrize(
    "first",
    [
        {"url": "not a URL"},
        {
            "url": "https://docs.example.com/mcp",
            "oauth": {"authServerMetadataUrl": "http://auth.example.com/metadata"},
        },
        {
            "url": "https://docs.example.com/mcp",
            "oauth": {"callbackUrl": "https://evil.example/callback"},
        },
        {"url": "http://256.0.0.1/mcp"},
        {"url": "https://xn--a.example/mcp"},
    ],
)
def test_rejected_http_predecessor_does_not_reserve_namespace(tmp_path, first):
    root = copy_fixture("mcp-valid", tmp_path)
    path = root / ".pi/mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"docs-api": first, "docs_api": {"command": "node"}}})
    )
    _, findings = lint(root, "--rule", "pi-mcp-valid")
    assert findings == []


def test_admitted_http_server_namespace_collision(tmp_path):
    root = copy_fixture("mcp-valid", tmp_path)
    path = root / ".pi/mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "docs-api": {"url": "https://docs.example.com:443/mcp"},
                    "docs_api": {"command": "node"},
                }
            }
        )
    )
    _, findings = lint(root, "--rule", "pi-mcp-valid")
    assert len(findings) == 1
    assert "conflicts" in findings[0]["message"]


@pytest.mark.parametrize("auth", [{"provider": "openai"}, {}, [], True, "provider", 1])
def test_stdio_with_url_property_still_rejects_project_auth(auth):
    assert "global mcp.json" in _problem(
        {"type": "stdio", "command": "node", "url": None, "auth": auth}
    )


@pytest.mark.parametrize("auth", [None, False, "", 0])
def test_stdio_with_url_property_accepts_falsy_auth(auth):
    assert _problem({"type": "stdio", "command": "node", "url": None, "auth": auth}) is None


@pytest.mark.parametrize("name,valid", [("\ufeff", False), ("\u0085", True), ("\x1c", True)])
def test_oauth_client_name_uses_javascript_whitespace(name, valid):
    problem = _problem({"url": "https://docs.example.com/mcp", "oauth": {"clientName": name}})
    assert (problem is None) is valid


def test_server_name_trailing_newline_is_rejected(tmp_path):
    root = copy_fixture("mcp-valid", tmp_path)
    path = root / ".pi/mcp.json"
    path.write_text(json.dumps({"mcpServers": {"docs\n": {"command": "node"}}}))
    _, findings = lint(root, "--rule", "pi-mcp-valid")
    assert len(findings) == 1
    assert "server name" in findings[0]["message"]


def test_pi_mcp_containment_and_exclusion(tmp_path):
    root = copy_fixture("mcp-valid", tmp_path)
    context = RepositoryContext(root, exclude_patterns=[".pi/mcp.json"])
    assert context.lint_tree.find(PiMcpBlock) == []
    outside = tmp_path / "external.json"
    outside.write_text('{"mcpServers": {"outside": {"command": "uvx"}}}')
    path = root / ".pi/mcp.json"
    path.unlink()
    path.symlink_to(outside)
    invalidate_read_caches()
    assert RepositoryContext(root).lint_tree.find(PiMcpBlock) == []


def test_pi_1_0_oauth_metadata_url_cli(tmp_path):
    root = copy_fixture("mcp-oauth-metadata", tmp_path)
    result, findings = lint(root, "--rule", "pi-mcp-valid", "--rule", "mcp-valid-json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(findings) == 3
    assert {finding["rule_id"] for finding in findings} == {"pi-mcp-valid"}
    assert all("oauth.authServerMetadataUrl must be a string" in f["message"] for f in findings)
    for name in ("null", "number", "object"):
        assert any(f"'{name}'" in f["message"] for f in findings)


@pytest.mark.parametrize("value", [None, False, 42, {}, []])
def test_oauth_metadata_url_requires_a_string(value):
    assert "oauth.authServerMetadataUrl must be a string" in _problem(
        {"url": "https://docs.example.com/mcp", "oauth": {"authServerMetadataUrl": value}}
    )


def test_stdio_ignores_oauth_metadata_url():
    assert _problem({"command": "node", "oauth": {"authServerMetadataUrl": 42}}) is None


def messages(findings):
    assert {f["rule_id"] for f in findings} <= {"pi-mcp-valid"}
    return {f["message"] for f in findings}


def test_pi_1_5_bom_prefixed_file_is_checked(tmp_path):
    root = copy_fixture("mcp-bom", tmp_path)
    assert (root / ".pi/mcp.json").read_bytes().startswith(b"\xef\xbb\xbf")
    _, findings = lint(root, "--rule", "pi-mcp-valid", "--rule", "mcp-valid-json")
    assert messages(findings) == {
        "Pi skips MCP server 'slow': timeout must be a positive number of seconds"
    }


def test_pi_1_5_project_overrides_cli(tmp_path):
    root = copy_fixture("mcp-overrides", tmp_path)
    _, findings = lint(root, "--rule", "pi-mcp-valid", "--rule", "mcp-valid-json")
    assert messages(findings) == {
        "Pi skips MCP server 'extra-keys': an override can only set enabled, exposure, "
        "toolExposure; add command or url to define a project server",
        "Pi skips MCP server 'bad-enabled': enabled must be a boolean",
        "Pi skips MCP server 'bad-exposure': exposure must be codemode, deferred, direct, "
        "hidden, or codemode-deferred",
        "Pi skips MCP server 'bad-tool-exposure': toolExposure must map tool names to "
        "supported exposure values",
    }


@pytest.mark.parametrize(
    "config,override",
    [
        ({}, True),
        ({"enabled": False, "exposure": "codemode-deferred"}, True),
        ({"type": None}, False),
        ({"url": None, "enabled": False}, False),
        ({"command": 42}, False),
    ],
)
def test_override_requires_absent_definition_keys(config, override):
    assert (_problem(config) is None) is override


@pytest.mark.parametrize("override_first", [True, False])
def test_override_reserves_namespace(tmp_path, override_first):
    # A valid override keeps the global "docs-api" loaded before any project
    # server, so "docs_api" conflicts with it wherever the override sits.
    root = copy_fixture("mcp-valid", tmp_path)
    path = root / ".pi/mcp.json"
    entries = [("docs-api", {"enabled": False}), ("docs_api", {"command": "node"})]
    if not override_first:
        entries.reverse()
    path.write_text(json.dumps({"mcpServers": dict(entries)}))
    _, findings = lint(root, "--rule", "pi-mcp-valid")
    assert messages(findings) == {
        "Pi skips MCP server 'docs_api': name conflicts with 'docs-api'; "
        "Pi treats hyphens and underscores as the same namespace"
    }


def test_invalid_override_reserves_no_namespace(tmp_path):
    root = copy_fixture("mcp-valid", tmp_path)
    path = root / ".pi/mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"docs-api": {"enabled": "no"}, "docs_api": {"command": "node"}}})
    )
    _, findings = lint(root, "--rule", "pi-mcp-valid")
    assert messages(findings) == {"Pi skips MCP server 'docs-api': enabled must be a boolean"}


def test_overrides_in_one_namespace_conflict(tmp_path):
    # Global names cannot clash, so only one override can match a global server.
    root = copy_fixture("mcp-valid", tmp_path)
    path = root / ".pi/mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"docs-api": {"enabled": False}, "docs_api": {"enabled": True}}})
    )
    _, findings = lint(root, "--rule", "pi-mcp-valid")
    assert messages(findings) == {
        "Pi skips MCP server 'docs_api': name conflicts with 'docs-api'; "
        "Pi treats hyphens and underscores as the same namespace"
    }


def test_pi_1_5_oauth_client_registration_cli(tmp_path):
    root = copy_fixture("mcp-client-registration", tmp_path)
    _, findings = lint(root, "--rule", "pi-mcp-valid", "--rule", "mcp-valid-json")
    invalid = 'oauth.clientRegistration must be "auto", "dcr", or "cimd"'
    combined = (
        'oauth.clientRegistration "cimd" cannot be combined with oauth.clientId or oauth.clientName'
    )
    assert messages(findings) == {
        f"Pi skips MCP server 'unknown': {invalid}",
        f"Pi skips MCP server 'null': {invalid}",
        f"Pi skips MCP server 'cimd-client-id': {combined}",
        f"Pi skips MCP server 'cimd-client-name': {combined}",
    }
