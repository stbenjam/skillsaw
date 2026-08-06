"""Conformance and routing tests for Agent Plugins portable MCP config."""

import json

from skillsaw.blocks import AgentPluginMcpBlock
from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity

from ._helpers import MCP_RULE, copy_fixture, lint_rules, messages_lower


def _contains(findings, *needles: str) -> bool:
    for finding in findings:
        message = finding.message.lower()
        if all(needle in message for needle in needles):
            return True
    return False


class TestMcpDocument:
    def test_all_supported_variants_and_loopback_urls_pass(self, tmp_path):
        repo = copy_fixture("agent-plugins/clean", tmp_path)
        assert lint_rules(repo, MCP_RULE) == []

    def test_missing_optional_mcp_file_passes(self, tmp_path):
        repo = copy_fixture("agent-plugins/metadata-lax", tmp_path)
        assert lint_rules(repo, MCP_RULE) == []

    def test_invalid_json_is_reported_at_component_boundary(self, tmp_path):
        repo = copy_fixture("agent-plugins/invalid-mcp-json", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        assert len(findings) == 1
        assert "json" in findings[0].message.lower()
        assert findings[0].file_path == repo / "mcp.json"

    def test_invalid_top_level_shape_is_reported(self, tmp_path):
        repo = copy_fixture("agent-plugins/invalid-mcp-top-level", tmp_path)
        findings = lint_rules(repo, MCP_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "mcpservers" in combined
        expected_words = ("fallbackservers", "unknown", "additional")
        assert any(word in combined for word in expected_words)

    def test_mcp_schema_version_must_match_manifest(self, tmp_path):
        repo = copy_fixture("agent-plugins/schema-mismatch", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        assert findings
        assert _contains(findings, "schema")
        combined = "\n".join(messages_lower(findings))
        assert "match" in combined or "unsupported" in combined
        assert not _contains(findings, "otherwise-valid")

    def test_mcp_location_must_be_a_regular_file(self, tmp_path):
        repo = copy_fixture("agent-plugins/wrong-kinds", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        assert findings
        assert _contains(findings, "mcp.json")
        assert any("file" in message for message in messages_lower(findings))

    def test_escaping_mcp_symlink_is_reported_but_never_parsed(self, tmp_path):
        fixture = copy_fixture("agent-plugins/containment", tmp_path)
        repo = fixture / "repo"
        assert (repo / "mcp.json").is_symlink()

        findings = lint_rules(repo, MCP_RULE)
        context = RepositoryContext(repo)

        assert findings
        assert any(
            "outside" in message or "within" in message or "contain" in message
            for message in messages_lower(findings)
        )
        assert context.lint_tree.find(AgentPluginMcpBlock) == []


class TestMcpServerEntries:
    def test_one_invalid_server_does_not_hide_valid_siblings(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        assert findings
        assert all(finding.severity is Severity.ERROR for finding in findings)
        assert not _contains(findings, "valid-sibling")
        assert _contains(findings, "absolute-command")
        assert _contains(findings, "insecure-remote")

    def test_commands_are_bare_tokens_or_contained_dot_paths(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        for server in (
            "absolute-command",
            "unprefixed-package-command",
            "escaping-command",
        ):
            assert _contains(findings, server), messages_lower(findings)

    def test_variant_fields_and_required_fields_are_enforced(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        for server in (
            "missing-command",
            "invalid-args",
            "invalid-env",
            "missing-url",
            "invalid-headers",
        ):
            assert _contains(findings, server), messages_lower(findings)

    def test_unhashable_type_is_reported_without_crashing(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        assert _contains(findings, "unhashable-type")

    def test_diagnostics_do_not_echo_invalid_secret_values(self, tmp_path):
        schema_base = "https://agent-plugins.org/schemas/1.0.0"
        secret = "sk-distinctive-schema-redaction-sentinel"
        manifest = {
            "$schema": f"{schema_base}/plugin.schema.json",
            "name": "secret-redaction",
        }
        mcp = {
            "$schema": f"{schema_base}/mcp.schema.json",
            "mcpServers": {
                "bad-args": {
                    "type": "stdio",
                    "command": "uvx",
                    "args": {"credential": secret},
                }
            },
        }
        (tmp_path / "plugin.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        (tmp_path / "mcp.json").write_text(
            json.dumps(mcp),
            encoding="utf-8",
        )

        findings = lint_rules(tmp_path, MCP_RULE)

        assert findings
        assert all(secret not in item.message for item in findings)

    def test_env_and_headers_reject_credentials_without_echoing_values(self, tmp_path):
        schema_base = "https://agent-plugins.org/schemas/1.0.0"
        env_secret = "r4Nd0m-V4lu3-Q8z2-W7k9"
        authorization_secret = "Bearer q7K9m2V4w8R3n6D1"
        structured_token = "ghp_aB3cD4eF5gH6iJ7kL8mN9pQ0rS1uV2wX3yZ4"
        structured_secret = f"{structured_token}:${{PLUGIN_ROOT}}"
        manifest = {
            "$schema": f"{schema_base}/plugin.schema.json",
            "name": "embedded-mcp-credentials",
        }
        mcp = {
            "$schema": f"{schema_base}/mcp.schema.json",
            "mcpServers": {
                "env-secret": {
                    "type": "stdio",
                    "command": "uvx",
                    "env": {"OPENAI_API_KEY": env_secret},
                },
                "authorization-secret": {
                    "type": "streamable-http",
                    "url": "https://example.com/mcp",
                    "headers": {"Authorization": authorization_secret},
                },
                "structured-header-secret": {
                    "type": "sse",
                    "url": "https://example.com/sse",
                    "headers": {"X-Trace-ID": structured_secret},
                },
            },
        }
        (tmp_path / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (tmp_path / "mcp.json").write_text(json.dumps(mcp), encoding="utf-8")

        findings = lint_rules(tmp_path, MCP_RULE)
        messages = "\n".join(finding.message for finding in findings)

        assert len(findings) == 3
        assert _contains(findings, "env-secret", "openai_api_key", "secret")
        assert _contains(findings, "authorization-secret", "authorization", "secret")
        assert _contains(findings, "structured-header-secret", "github", "secret")
        for secret in (env_secret, authorization_secret, structured_secret):
            assert secret not in messages

    def test_env_and_header_placeholders_are_not_credentials(self, tmp_path):
        schema_base = "https://agent-plugins.org/schemas/1.0.0"
        manifest = {
            "$schema": f"{schema_base}/plugin.schema.json",
            "name": "mcp-credential-placeholders",
        }
        mcp = {
            "$schema": f"{schema_base}/mcp.schema.json",
            "mcpServers": {
                "stdio": {
                    "type": "stdio",
                    "command": "uvx",
                    "env": {"OPENAI_API_KEY": "${OPENAI_API_KEY}"},
                },
                "remote": {
                    "type": "streamable-http",
                    "url": "https://example.com/mcp",
                    "headers": {
                        "Authorization": "Bearer ${AUTH_TOKEN}",
                        "X-API-Key": "<your-api-key>",
                    },
                },
            },
        }
        (tmp_path / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (tmp_path / "mcp.json").write_text(json.dumps(mcp), encoding="utf-8")

        assert lint_rules(tmp_path, MCP_RULE) == []

    def test_cwd_forms_and_containment_are_enforced(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        for server in (
            "bad-working-directory",
            "escaping-plugin-directory",
            "escaping-data-directory",
        ):
            assert _contains(findings, server), messages_lower(findings)

    def test_safe_parent_normalization_within_placeholder_roots_passes(self, tmp_path):
        schema_base = "https://agent-plugins.org/schemas/1.0.0"
        manifest = {
            "$schema": f"{schema_base}/plugin.schema.json",
            "name": "normalized-working-directories",
        }
        mcp = {
            "$schema": f"{schema_base}/mcp.schema.json",
            "mcpServers": {
                "plugin-root": {
                    "type": "stdio",
                    "command": "uvx",
                    "cwd": "${PLUGIN_ROOT}/work/../work",
                },
                "plugin-data": {
                    "type": "stdio",
                    "command": "uvx",
                    "cwd": "${PLUGIN_DATA}/cache/../cache",
                },
            },
        }
        (tmp_path / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (tmp_path / "mcp.json").write_text(json.dumps(mcp), encoding="utf-8")

        assert lint_rules(tmp_path, MCP_RULE) == []

    def test_windows_separators_cannot_hide_cross_root_traversal(self, tmp_path):
        schema_base = "https://agent-plugins.org/schemas/1.0.0"
        manifest = {
            "$schema": f"{schema_base}/plugin.schema.json",
            "name": "portable-containment",
        }
        mcp = {
            "$schema": f"{schema_base}/mcp.schema.json",
            "mcpServers": {
                "escaping-command": {
                    "type": "stdio",
                    "command": r"./safe\..\..\outside",
                },
                "escaping-data-cwd": {
                    "type": "stdio",
                    "command": "uvx",
                    "cwd": r"${PLUGIN_DATA}/safe\..\..\outside",
                },
            },
        }
        (tmp_path / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (tmp_path / "mcp.json").write_text(json.dumps(mcp), encoding="utf-8")

        findings = lint_rules(tmp_path, MCP_RULE)

        assert _contains(findings, "escaping-command")
        assert _contains(findings, "escaping-data-cwd")

    def test_reserved_environment_names_are_rejected(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        reserved = [
            finding.message.lower()
            for finding in findings
            if "reserved-environment" in finding.message.lower()
        ]
        assert reserved
        assert any("plugin_root" in message for message in reserved)
        assert any("plugin_data" in message for message in reserved)

    def test_remote_url_policy_is_enforced(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        for server in (
            "insecure-remote",
            "userinfo-remote",
            "fragment-remote",
        ):
            assert _contains(findings, server), messages_lower(findings)

    def test_headers_are_fields_and_case_insensitively_unique(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        assert _contains(findings, "duplicate-headers")
        assert _contains(findings, "invalid-header")

    def test_server_variants_are_closed(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
        findings = lint_rules(repo, MCP_RULE)

        assert _contains(findings, "mixed-variant")
        assert _contains(findings, "unsupported-variant")


def test_agent_mcp_routes_without_generic_duplicate_validation(tmp_path):
    repo = copy_fixture("agent-plugins/broken-mcp", tmp_path)
    findings = lint_rules(repo, MCP_RULE, "mcp-valid-json", "mcp-prohibited")
    ids = {finding.rule_id for finding in findings}

    assert MCP_RULE in ids
    assert "mcp-prohibited" in ids
    assert "mcp-valid-json" not in ids
