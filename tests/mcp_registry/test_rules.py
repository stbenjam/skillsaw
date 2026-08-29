"""Conformance tests for MCP Registry server.json rules."""

import json

import pytest

from skillsaw.context import RepositoryType
from skillsaw.formats.mcp_registry import MCP_REGISTRY_SCHEMA_ID
from skillsaw.rule import Severity

from ._helpers import (
    NPM_NAME_RULE,
    SEMVER_RULE,
    VALID_RULE,
    copy_fixture,
    lint_rules,
    messages_lower,
)


def _load_server(repo):
    path = repo / "server.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _write_server(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _for_rule(findings, rule_id):
    return [finding for finding in findings if finding.rule_id == rule_id]


class TestMcpRegistrySchemaRule:
    def test_clean_publisher_metadata_passes(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)

        assert lint_rules(repo, VALID_RULE) == []

    def test_malformed_json_is_reported_when_type_is_forced(self, tmp_path):
        (tmp_path / "server.json").write_text('{"name": ', encoding="utf-8")

        findings = lint_rules(
            tmp_path,
            VALID_RULE,
            repo_types={RepositoryType.MCP_REGISTRY},
        )

        assert len(findings) == 1
        assert "invalid json" in findings[0].message.lower()

    def test_non_object_json_is_reported_when_type_is_forced(self, tmp_path):
        (tmp_path / "server.json").write_text("[]", encoding="utf-8")

        findings = lint_rules(
            tmp_path,
            VALID_RULE,
            repo_types={RepositoryType.MCP_REGISTRY},
        )

        assert len(findings) == 1
        assert "json object" in findings[0].message.lower()

    def test_missing_schema_is_reported_after_shape_detection(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        del data["$schema"]
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("missing '$schema'" in message for message in messages_lower(findings))

    def test_unsupported_schema_version_is_reported(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["$schema"] = (
            "https://static.modelcontextprotocol.io/schemas/" "2026-01-01/server.schema.json"
        )
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        combined = "\n".join(messages_lower(findings))
        assert "unsupported" in combined
        assert "2025-12-11" in combined

    def test_schema_constraints_are_reported_without_values(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["description"] = ""
        data["repository"]["url"] = "not a uri"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "does not conform" in combined
        assert "description" in combined
        assert "repository.url" in combined
        assert "not a uri" not in combined

    @pytest.mark.parametrize(
        "name",
        [
            "example/weather",
            ".com.example/weather",
            "com..example/weather",
            "com.example./weather",
            "com.example/-weather",
            "com.example/weather_",
            "com.example/wea?ther",
            "com_example.weather/service",
        ],
    )
    def test_reverse_dns_namespace_and_server_boundaries_are_enforced(self, tmp_path, name):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["name"] = name
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("'name'" in message for message in messages_lower(findings))

    @pytest.mark.parametrize("registry_type", ["npm", "pypi", "cargo", "oci", "nuget", "mcpb"])
    def test_current_registry_types_pass(self, tmp_path, registry_type):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = registry_type
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    def test_unknown_registry_type_is_rejected_but_configurable(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = "company-internal"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        configured = lint_rules(
            repo,
            VALID_RULE,
            rule_config={
                VALID_RULE: {
                    "registry-types": [
                        "npm",
                        "pypi",
                        "cargo",
                        "oci",
                        "nuget",
                        "mcpb",
                        "company-internal",
                    ]
                }
            },
        )

        assert any("registrytype" in message for message in messages_lower(findings))
        assert configured == []

    @pytest.mark.parametrize("transport", ["stdio", "streamable-http", "sse"])
    def test_package_transport_enum_passes(self, tmp_path, transport):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["transport"] = {"type": transport}
        if transport != "stdio":
            data["packages"][0]["transport"]["url"] = "https://weather.example.com/mcp"
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize("transport", ["streamable-http", "sse"])
    def test_remote_transport_enum_passes(self, tmp_path, transport):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["remotes"][0]["type"] = transport
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    def test_invalid_package_and_remote_transports_are_precise(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["transport"] = {"type": "websocket"}
        data["remotes"] = [{"type": "stdio"}]
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "packages[0].transport.type" in combined
        assert "remotes[0].type" in combined

    @pytest.mark.parametrize(
        "version",
        [
            "latest",
            "^1.2.3",
            "~1.2.3",
            ">=1.2.3",
            "1.x",
            "1.2.*",
            "1.0 - 2.0",
            "1.2 || 1.3",
        ],
    )
    def test_top_level_version_ranges_are_errors(self, tmp_path, version):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["version"] = version
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("exact release" in message for message in messages_lower(findings))

    def test_version_range_does_not_hide_an_unrelated_schema_error(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["version"] = "^" + "1" * 260
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "exact release" in combined
        assert "at most 255" in combined

    def test_package_version_range_is_an_error(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["version"] = "1.x"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].version" in message for message in messages_lower(findings))

    def test_non_semver_label_containing_x_is_not_misread_as_a_range(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["version"] = "release.x"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert not any("exact release" in message for message in messages_lower(findings))


class TestMcpRegistrySemverRule:
    @pytest.mark.parametrize(
        "version",
        ["0.0.0", "1.2.3", "1.2.3-beta.1", "1.2.3-beta.1+build.4"],
    )
    def test_strict_semver_passes(self, tmp_path, version):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["version"] = version
        _write_server(path, data)

        assert _for_rule(lint_rules(repo, SEMVER_RULE), SEMVER_RULE) == []

    @pytest.mark.parametrize("version", ["2025-12-11", "v1.2.3", "1.2", "1.2.3-01"])
    def test_non_semver_exact_versions_warn(self, tmp_path, version):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["version"] = version
        _write_server(path, data)

        findings = _for_rule(lint_rules(repo, SEMVER_RULE), SEMVER_RULE)

        assert len(findings) == 1
        assert findings[0].severity is Severity.WARNING
        assert "semantic versioning" in findings[0].message.lower()

    def test_range_error_is_not_duplicated_as_semver_warning(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["version"] = "^1.2.3"
        _write_server(path, data)

        findings = lint_rules(repo, SEMVER_RULE)

        assert _for_rule(findings, SEMVER_RULE) == []
        assert _for_rule(findings, VALID_RULE)


class TestMcpRegistryNpmNameRule:
    def test_matching_adjacent_package_passes(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)

        assert lint_rules(repo, NPM_NAME_RULE) == []

    def test_matching_workspace_package_passes(self, tmp_path):
        repo = copy_fixture("mcp-registry/monorepo", tmp_path)

        assert lint_rules(repo, NPM_NAME_RULE) == []

    def test_shared_package_is_checked_for_each_server_identity(self, tmp_path):
        package = {
            "name": "@example/weather-mcp",
            "version": "1.0.0",
            "mcpName": "com.example/first",
        }
        (tmp_path / "package.json").write_text(json.dumps(package), encoding="utf-8")
        for directory, server_name in (
            ("one", "com.example/first"),
            ("two", "com.example/second"),
        ):
            server = {
                "$schema": MCP_REGISTRY_SCHEMA_ID,
                "name": server_name,
                "description": "A server sharing one local npm package.",
                "version": "1.0.0",
                "packages": [
                    {
                        "registryType": "npm",
                        "identifier": "@example/weather-mcp",
                        "version": "1.0.0",
                        "transport": {"type": "stdio"},
                    }
                ],
            }
            server_dir = tmp_path / directory
            server_dir.mkdir()
            _write_server(server_dir / "server.json", server)

        findings = _for_rule(lint_rules(tmp_path, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert "com.example/second" in findings[0].message

    @pytest.mark.parametrize("replacement", [{}, {"mcpName": 7}, {"mcpName": "wrong/name"}])
    def test_missing_invalid_or_mismatched_mcp_name_is_reported(self, tmp_path, replacement):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        package_path = repo / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package.pop("mcpName")
        package.update(replacement)
        package_path.write_text(json.dumps(package), encoding="utf-8")

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == package_path
        assert "mcpname" in findings[0].message.lower()

    def test_invalid_adjacent_package_json_is_reported(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        package_path = repo / "package.json"
        package_path.write_text('{"name": ', encoding="utf-8")

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == package_path
        assert "cannot be verified" in findings[0].message.lower()

    def test_non_object_adjacent_package_json_is_reported(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        package_path = repo / "package.json"
        package_path.write_text("[]", encoding="utf-8")

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == package_path
        assert "json object" in findings[0].message.lower()

    def test_external_npm_package_without_local_manifest_is_quiet(self, tmp_path):
        server = {
            "$schema": MCP_REGISTRY_SCHEMA_ID,
            "name": "com.example/weather",
            "description": "Uses a package published from another repository.",
            "version": "1.0.0",
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@external/weather-mcp",
                    "transport": {"type": "stdio"},
                }
            ],
        }
        (tmp_path / "server.json").write_text(json.dumps(server), encoding="utf-8")

        assert lint_rules(tmp_path, NPM_NAME_RULE) == []

    def test_non_npm_package_does_not_consult_package_json(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = "pypi"
        _write_server(path, data)
        (repo / "package.json").write_text('{"name": ', encoding="utf-8")

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []
