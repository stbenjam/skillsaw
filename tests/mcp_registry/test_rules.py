"""Conformance tests for MCP Registry server.json rules."""

import json
from dataclasses import MISSING, fields

import pytest
from jsonschema.exceptions import ValidationError

from skillsaw.context import RepositoryType
from skillsaw.formats.mcp_registry import (
    MCP_REGISTRY_SCHEMA_ID,
    MCP_REGISTRY_SCHEMA_PROFILES,
    MCP_REGISTRY_SCHEMA_VERSIONS,
    mcp_registry_schema_id,
)
from skillsaw.rule import Severity
from skillsaw.rules.builtin.mcp_registry._helpers import (
    is_loopback_hostname,
    is_release_source_placeholder,
    schema_error_summary,
)
from skillsaw.rules.builtin.mcp_registry.npm_name_match import McpRegistryNpmNameMatchRule
from skillsaw.rules.builtin.mcp_registry.server_json_valid import (
    _SEMANTIC_POLICIES,
    _SemanticPolicy,
)

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
    @pytest.mark.parametrize("value", ["${VERSION}", "{{VERSION}}", "<<Version>>"])
    def test_release_source_placeholder_forms_are_exact(self, value):
        assert is_release_source_placeholder(value)

    @pytest.mark.parametrize(
        "value",
        [
            "v${VERSION}",
            "${VERSION}-rc",
            "{VERSION}",
            "${{ github.ref }}",
            "{{}}",
            "<<../x>>",
            "<<Version>>extra",
            "latest",
            "*",
            None,
        ],
    )
    def test_release_source_placeholder_near_misses_remain_values(self, value):
        assert not is_release_source_placeholder(value)

    def test_every_schema_version_has_an_explicit_semantic_policy(self):
        assert frozenset(_SEMANTIC_POLICIES) == MCP_REGISTRY_SCHEMA_VERSIONS

    def test_mapping_policy_default_uses_a_dataclass_factory(self):
        policy_field = next(
            candidate
            for candidate in fields(_SemanticPolicy)
            if candidate.name == "canonical_registry_base_urls"
        )

        assert policy_field.default is MISSING
        assert policy_field.default_factory is not MISSING
        assert policy_field.default_factory() == {}

    def test_clean_publisher_metadata_passes(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize("version", sorted(MCP_REGISTRY_SCHEMA_VERSIONS))
    def test_each_released_schema_validates_its_native_document(self, tmp_path, version):
        repo = copy_fixture(f"mcp-registry/schema-versions/{version}", tmp_path)

        assert lint_rules(repo, VALID_RULE, SEMVER_RULE, NPM_NAME_RULE) == []

    @pytest.mark.parametrize("placeholder", ["${VERSION}", "{{VERSION}}", "<<Version>>"])
    def test_publish_time_placeholders_pass_all_registry_rules(self, tmp_path, placeholder):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["name"] = placeholder
        data["version"] = placeholder
        data["packages"][0]["identifier"] = placeholder
        data["packages"][0]["version"] = placeholder
        data["packages"].append(
            {
                "registryType": "mcpb",
                "identifier": placeholder,
                "version": placeholder,
                "fileSha256": placeholder,
                "transport": {"type": "stdio"},
            }
        )
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE, SEMVER_RULE, NPM_NAME_RULE) == []

    def test_placeholder_sanitizing_retains_unrelated_schema_errors(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["name"] = "${NAME}"
        data["version"] = "${VERSION}"
        data["description"] = "x" * 101
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("description" in message for message in messages_lower(findings))

    def test_initial_schema_sanitizes_its_native_hash_field(self, tmp_path):
        repo = copy_fixture("mcp-registry/schema-versions/2025-07-09", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registry_type"] = "mcpb"
        package["identifier"] = "${IDENTIFIER}"
        package["version"] = "${VERSION}"
        package["file_sha256"] = "${FILE_SHA256}"
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize(
        ("fixture_version", "registry_type"),
        [("2025-10-11", "oci"), ("2025-10-17", "mcpb")],
    )
    def test_placeholder_does_not_override_forbidden_version_field(
        self, tmp_path, fixture_version, registry_type
    ):
        repo = copy_fixture(f"mcp-registry/schema-versions/{fixture_version}", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registryType"] = registry_type
        package["version"] = "${VERSION}"
        if registry_type == "mcpb":
            data["$schema"] = mcp_registry_schema_id("2025-10-11")
            package["identifier"] = "https://example.com/server.mcpb"
            package["fileSha256"] = "0" * 64
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("must be omitted" in message for message in messages_lower(findings))

    def test_embedded_placeholder_in_name_is_still_invalid(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["name"] = "prefix-${NAME}"
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE)

    def test_initial_snake_case_schema_keeps_npm_ownership_check(self, tmp_path):
        repo = copy_fixture("mcp-registry/schema-versions/2025-07-09", tmp_path)
        package_path = repo / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["mcpName"] = "io.github.example/something-else"
        _write_server(package_path, package)

        findings = lint_rules(repo, NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].rule_id == NPM_NAME_RULE
        assert "exactly match" in findings[0].message.lower()

    def test_initial_schema_uses_native_hash_field_in_semantic_diagnostic(self, tmp_path):
        repo = copy_fixture("mcp-registry/schema-versions/2025-07-09", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registry_type"] = "mcpb"
        package["identifier"] = "https://example.com/releases/weather.mcpb"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].file_sha256" in message for message in messages_lower(findings))

    @pytest.mark.parametrize("version", ["2025-07-09", "2025-09-16", "2025-09-29"])
    def test_pre_icon_schemas_do_not_apply_later_icon_policy(self, tmp_path, version):
        repo = copy_fixture(f"mcp-registry/schema-versions/{version}", tmp_path)
        path, data = _load_server(repo)
        data["icons"] = [{"src": "http://example.com/icon.png"}]
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    def test_mcpb_package_version_transition_is_version_specific(self, tmp_path):
        repo = copy_fixture("mcp-registry/schema-versions/2025-10-17", tmp_path)
        path, data = _load_server(repo)
        data["$schema"] = mcp_registry_schema_id("2025-10-11")
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any(
            "version" in message and "mcpb" in message for message in messages_lower(findings)
        )

    @pytest.mark.parametrize("version", ["2025-10-11", "2025-10-17", "2025-12-11"])
    def test_oci_package_version_stays_in_identifier(self, tmp_path, version):
        repo = copy_fixture("mcp-registry/schema-versions/2025-10-11", tmp_path)
        path, data = _load_server(repo)
        data["$schema"] = mcp_registry_schema_id(version)
        data["packages"][0]["version"] = "1.0.0"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any(
            "version" in message and "oci" in message for message in messages_lower(findings)
        )

    @pytest.mark.parametrize("version", ["2025-10-11", "2025-10-17", "2025-12-11"])
    @pytest.mark.parametrize("registry_type", ["pypi", "cargo", "nuget"])
    def test_registry_packages_that_publish_versions_require_one(
        self, tmp_path, version, registry_type
    ):
        repo = copy_fixture("mcp-registry/schema-versions/2025-10-11", tmp_path)
        path, data = _load_server(repo)
        data["$schema"] = mcp_registry_schema_id(version)
        data["packages"][0]["registryType"] = registry_type
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].version" in message for message in messages_lower(findings))

    def test_registry_managed_fields_follow_the_schema_transition(self, tmp_path):
        legacy = copy_fixture("mcp-registry/schema-versions/2025-09-16", tmp_path)
        legacy_path, legacy_data = _load_server(legacy)
        legacy_data["status"] = "active"
        legacy_data["_meta"] = {"io.modelcontextprotocol.registry/official": {}}
        _write_server(legacy_path, legacy_data)

        current = copy_fixture("mcp-registry/schema-versions/2025-09-29", tmp_path)
        current_path, current_data = _load_server(current)
        current_data["status"] = "active"
        current_data["_meta"] = {"io.modelcontextprotocol.registry/official": {}}
        _write_server(current_path, current_data)

        assert lint_rules(legacy, VALID_RULE) == []
        current_messages = messages_lower(lint_rules(current, VALID_RULE))
        assert any("'status' is registry-managed" in message for message in current_messages)
        assert any(
            "official" in message and "registry-managed" in message for message in current_messages
        )

    @pytest.mark.parametrize(
        ("version", "old_field", "new_field"),
        [
            ("2025-07-09", "registry_type", "registryType"),
            ("2025-09-16", "registryType", "registry_type"),
        ],
    )
    def test_declared_schema_enforces_its_field_vocabulary(
        self, tmp_path, version, old_field, new_field
    ):
        repo = copy_fixture(f"mcp-registry/schema-versions/{version}", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0][new_field] = data["packages"][0].pop(old_field)
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("does not conform" in message for message in messages_lower(findings))

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
        # A future document may violate the current schema and semantics. It
        # must not be interpreted using a version it did not declare.
        data["name"] = "not-reverse-dns"
        data["description"] = ""
        data["version"] = "latest"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE, SEMVER_RULE, NPM_NAME_RULE)

        assert len(findings) == 1
        message = findings[0].message.lower()
        assert "unsupported" in message
        assert "2025-12-11" in message
        assert "does not conform" not in message

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

    def test_malformed_uri_authority_is_reported(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["repository"]["url"] = "https://["
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "repository.url" in combined
        assert "valid uri" in combined

    def test_repeated_uri_fragment_delimiter_is_reported(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["websiteUrl"] = "https://example.com/#first#second"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "websiteurl" in combined
        assert "valid uri" in combined

    @pytest.mark.parametrize(
        "website_url", ["https://[2001:db8::1]/weather", "urn:example:weather"]
    )
    def test_ipv6_and_opaque_website_uris_pass(self, tmp_path, website_url):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["websiteUrl"] = website_url
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize(
        "src",
        [
            "http://example.com/icon.png",
            "file:/tmp/icon.png",
            "https:icon.png",
            "https:/icon.png",
        ],
    )
    def test_icon_sources_must_use_https(self, tmp_path, src):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["icons"] = [{"src": src}]
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any(
            "icons[0].src must use an https uri" in message for message in messages_lower(findings)
        )

    def test_https_icon_source_passes(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["icons"] = [{"src": "https://example.com/icon.png"}]
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize("subfolder", ["/tmp/server", "../../server", "src//server"])
    def test_repository_subfolder_must_be_clean_and_relative(self, tmp_path, subfolder):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["repository"]["subfolder"] = subfolder
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("repository.subfolder" in message for message in messages_lower(findings))

    def test_clean_repository_subfolder_passes(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["repository"]["subfolder"] = "packages/weather-server"
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

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
        package = data["packages"][0]
        package["registryType"] = registry_type
        if registry_type == "oci":
            package["identifier"] = "ghcr.io/example/weather:1.2.3"
            del package["version"]
        elif registry_type == "mcpb":
            package["identifier"] = (
                "https://github.com/example/weather/releases/download/v1.2.3/weather.mcpb"
            )
            package["fileSha256"] = "0" * 64
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize(
        ("registry_type", "base_url"),
        [
            ("npm", "https://registry.npmjs.org"),
            ("pypi", "https://pypi.org"),
            ("nuget", "https://api.nuget.org/v3/index.json"),
            ("cargo", "https://crates.io"),
        ],
    )
    def test_current_canonical_registry_base_urls_pass(self, tmp_path, registry_type, base_url):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registryType"] = registry_type
        package["registryBaseUrl"] = base_url
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize(
        ("registry_type", "base_url"),
        [
            ("npm", "https://pypi.org"),
            ("pypi", "https://pypi.org/"),
            ("nuget", "https://api.nuget.org"),
            ("cargo", "https://example.com/crates"),
        ],
    )
    def test_noncanonical_registry_base_urls_are_reported(self, tmp_path, registry_type, base_url):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registryType"] = registry_type
        package["registryBaseUrl"] = base_url
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("canonical public" in message for message in messages_lower(findings))

    @pytest.mark.parametrize("version", sorted(MCP_REGISTRY_SCHEMA_VERSIONS - {"2025-12-11"}))
    @pytest.mark.parametrize(
        "base_url", ["https://api.nuget.org", "https://api.nuget.org/v3/index.json"]
    )
    def test_legacy_nuget_accepts_both_publisher_base_urls(self, tmp_path, version, base_url):
        repo = copy_fixture(f"mcp-registry/schema-versions/{version}", tmp_path)
        path, data = _load_server(repo)
        profile = MCP_REGISTRY_SCHEMA_PROFILES[version]
        data["packages"] = [
            {
                profile.registry_type_field: "nuget",
                profile.registry_base_url_field: base_url,
                "identifier": "Example.Weather",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            }
        ]
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    def test_custom_registry_type_does_not_inherit_public_base_policy(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registryType"] = "company-internal"
        package["registryBaseUrl"] = "https://packages.example.com"
        _write_server(path, data)

        findings = lint_rules(
            repo,
            VALID_RULE,
            rule_config={VALID_RULE: {"registry-types": ["company-internal"]}},
        )

        assert findings == []

    def test_initial_schema_allows_legacy_base_and_non_mcpb_hash_fields(self, tmp_path):
        repo = copy_fixture("mcp-registry/schema-versions/2025-07-09", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registry_base_url"] = "https://registry.npmjs.org"
        package["file_sha256"] = "0" * 64
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize("registry_type", ["oci", "mcpb"])
    def test_initial_schema_allows_legacy_direct_package_base_url(self, tmp_path, registry_type):
        repo = copy_fixture("mcp-registry/schema-versions/2025-07-09", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registry_type"] = registry_type
        package["registry_base_url"] = "https://github.com"
        if registry_type == "oci":
            package["identifier"] = "ghcr.io/example/weather:1.0.0"
        else:
            package["identifier"] = "https://example.com/weather.mcpb"
            package["file_sha256"] = "0" * 64
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize("version", ["2025-10-11", "2025-10-17", "2025-12-11"])
    @pytest.mark.parametrize("registry_type", ["oci", "mcpb"])
    def test_modern_oci_and_mcpb_packages_forbid_registry_base_url(
        self, tmp_path, version, registry_type
    ):
        repo = copy_fixture(f"mcp-registry/schema-versions/{version}", tmp_path)
        path, data = _load_server(repo)
        package = {
            "registryType": registry_type,
            "registryBaseUrl": "https://github.com",
            "transport": {"type": "stdio"},
        }
        if registry_type == "oci":
            package["identifier"] = "ghcr.io/example/weather:1.2.3"
        else:
            package["identifier"] = "https://example.com/weather.mcpb"
            package["fileSha256"] = "0" * 64
        data["packages"] = [package]
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("omitted for oci and mcpb" in message for message in messages_lower(findings))

    @pytest.mark.parametrize("version", ["2025-10-11", "2025-10-17"])
    @pytest.mark.parametrize("registry_type", ["npm", "pypi", "nuget", "oci"])
    def test_10_series_non_mcpb_packages_forbid_file_hash(self, tmp_path, version, registry_type):
        repo = copy_fixture(f"mcp-registry/schema-versions/{version}", tmp_path)
        path, data = _load_server(repo)
        package = {
            "registryType": registry_type,
            "identifier": "example-weather",
            "fileSha256": "0" * 64,
            "transport": {"type": "stdio"},
        }
        if registry_type == "oci":
            package["identifier"] = "ghcr.io/example/weather:1.2.3"
        else:
            package["version"] = "1.2.3"
        data["packages"] = [package]
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("unless the package is mcpb" in message for message in messages_lower(findings))

    @pytest.mark.parametrize("registry_type", ["npm", "pypi", "nuget", "cargo", "oci"])
    @pytest.mark.parametrize("file_hash", ["0" * 64, "${FILE_SHA256}"])
    def test_current_non_mcpb_packages_forbid_file_hash(self, tmp_path, registry_type, file_hash):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registryType"] = registry_type
        package["fileSha256"] = file_hash
        if registry_type == "oci":
            package["identifier"] = "ghcr.io/example/weather:1.2.3"
            del package["version"]
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("unless the package is mcpb" in message for message in messages_lower(findings))

    @pytest.mark.parametrize(
        ("identifier", "valid"),
        [
            ("https://example.com/releases/server.mcpb", True),
            ("https://example.com/releases/MCP-package.zip", True),
            ("https://example.com/mcp/{{VERSION}}/server.zip", True),
            ("${MCPB_URL}", True),
            ("http://example.com/releases/server.mcpb", False),
            ("https://example.com/releases/server.zip", False),
            ("not-a-url-with-mcp", False),
        ],
    )
    def test_mcpb_identifier_constraints(self, tmp_path, identifier, valid):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["registryType"] = "mcpb"
        package["identifier"] = identifier
        package["fileSha256"] = "0" * 64
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        identifier_findings = [
            message for message in messages_lower(findings) if "packages[0].identifier" in message
        ]

        assert bool(identifier_findings) == (not valid)

    def test_mcpb_package_requires_integrity_hash(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = "mcpb"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].filesha256" in message for message in messages_lower(findings))

    def test_unknown_registry_type_is_rejected_but_configurable(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = "company-internal"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        configured = lint_rules(
            repo,
            VALID_RULE,
            rule_config={VALID_RULE: {"registry-types": ["company-internal"]}},
        )

        assert any("registrytype" in message for message in messages_lower(findings))
        assert configured == []

    def test_configured_registry_types_are_sanitized_in_diagnostics(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = "company-internal"
        _write_server(path, data)

        findings = lint_rules(
            repo,
            VALID_RULE,
            rule_config={
                VALID_RULE: {"registry-types": ["npm", "escape\x1b[31m", "bidi\u202evalue"]}
            },
        )
        combined = "\n".join(finding.message for finding in findings)

        assert "\x1b" not in combined
        assert "\u202e" not in combined
        assert "\N{REPLACEMENT CHARACTER}" in combined

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

    def test_package_and_remote_url_templates_must_be_structurally_valid(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["transport"] = {
            "type": "streamable-http",
            "url": "https://[",
        }
        data["remotes"][0]["url"] = "https://["
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "packages[0].transport.url" in combined
        assert "remotes[0].url" in combined

    @pytest.mark.parametrize(
        "url",
        [
            "https://{host",
            "ftp://example.com/mcp",
            "https:/mcp",
            "https://example.com:70000/mcp",
            " https://example.com/mcp",
        ],
    )
    def test_package_and_remote_url_templates_reject_invalid_edges(self, tmp_path, url):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["transport"] = {"type": "streamable-http", "url": url}
        data["remotes"][0]["url"] = url
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "packages[0].transport.url" in combined
        assert "remotes[0].url" in combined

    def test_package_and_remote_url_templates_allow_declared_variables(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        template = "https://{host}:{port}/mcp/{path}?token={token}"
        data["packages"][0]["transport"] = {
            "type": "streamable-http",
            "url": template,
        }
        data["packages"][0]["environmentVariables"] = [
            {"name": variable} for variable in ("host", "port", "path", "token")
        ]
        data["remotes"][0].update(
            {
                "url": template,
                "variables": {variable: {} for variable in ("host", "port", "path", "token")},
            }
        )
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize("suffix", ["?mode=test", "#fragment"])
    def test_port_placeholder_before_query_or_fragment_is_valid(self, tmp_path, suffix):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        url = f"https://example.com:{{port}}{suffix}"
        data["packages"][0]["transport"] = {"type": "streamable-http", "url": url}
        data["packages"][0]["environmentVariables"] = [{"name": "port"}]
        data["remotes"][0].update({"url": url, "variables": {"port": {}}})
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize(
        ("field", "argument", "variable"),
        [
            ("environmentVariables", {"name": "host"}, "host"),
            ("runtimeArguments", {"type": "named", "name": "--port"}, "--port"),
            ("runtimeArguments", {"type": "positional", "valueHint": "path"}, "path"),
            ("packageArguments", {"type": "named", "name": "--tenant"}, "--tenant"),
            ("packageArguments", {"type": "positional", "valueHint": "tenant"}, "tenant"),
        ],
    )
    def test_package_url_variables_use_official_declaration_fields(
        self, tmp_path, field, argument, variable
    ):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["transport"] = {
            "type": "streamable-http",
            "url": f"https://example.com/{{{variable}}}",
        }
        package[field] = [argument]
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    def test_initial_schema_uses_snake_case_package_variable_fields(self, tmp_path):
        repo = copy_fixture("mcp-registry/schema-versions/2025-07-09", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["transport"] = {
            "type": "streamable-http",
            "url": "https://{host}:{--port}/{path}",
        }
        package["environment_variables"] = [{"name": "host"}]
        package["runtime_arguments"] = [{"type": "named", "name": "--port"}]
        package["package_arguments"] = [{"type": "positional", "value_hint": "path"}]
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    def test_undefined_package_and_remote_url_variables_are_reported(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["transport"] = {
            "type": "streamable-http",
            "url": "https://{host}/{missing}",
        }
        data["packages"][0]["environmentVariables"] = [{"name": "host"}]
        data["remotes"][0].update(
            {
                "url": "https://{host}/{missing}",
                "variables": {"host": {}},
            }
        )
        _write_server(path, data)

        combined = "\n".join(messages_lower(lint_rules(repo, VALID_RULE)))

        assert "packages[0].transport.url" in combined
        assert "declared package" in combined
        assert "remotes[0].url" in combined
        assert "remote variables" in combined

    def test_unrelated_nested_variables_do_not_satisfy_package_url(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        package = data["packages"][0]
        package["transport"] = {
            "type": "streamable-http",
            "url": "https://{host}/mcp",
            "variables": {"host": {}},
            "headers": [{"name": "host", "value": "example.com"}],
        }
        package["packageArguments"] = [
            {"type": "positional", "value": "{host}", "variables": {"host": {}}}
        ]
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("declared package" in message for message in messages_lower(findings))

    def test_remote_variables_extension_is_honored_for_older_schema(self, tmp_path):
        repo = copy_fixture("mcp-registry/schema-versions/2025-10-17", tmp_path)
        path, data = _load_server(repo)
        data["remotes"] = [
            {
                "type": "streamable-http",
                "url": "https://dev.azure.com/{organization}/mcp",
                "variables": {"organization": {"description": "Azure organization"}},
            }
        ]
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/mcp",
            "https://localhost/mcp",
            "https://LOCALHOST./mcp",
            "https://tenant.localhost/mcp",
            "https://127.0.0.2/mcp",
            "https://127.1/mcp",
            "https://127.1./mcp",
            "https://127.0.1/mcp",
            "https://0177.0.0.1/mcp",
            "https://0x7f000001/mcp",
            "https://2130706433/mcp",
            "https://%31%32%37.0.0.1/mcp",
            "https://127%2e0%2e0%2e1/mcp",
            "https://0x7f%2e1/mcp",
            "https://127%E3%80%820%E3%80%820%E3%80%821/mcp",
            "https://%EF%BC%91%EF%BC%92%EF%BC%97.%EF%BC%90.%EF%BC%90.%EF%BC%91/mcp",
            "https://[::1]/mcp",
        ],
    )
    def test_remote_urls_require_https_and_reject_loopback(self, tmp_path, url):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["remotes"][0]["url"] = url
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("remotes[0].url" in message for message in messages_lower(findings))

    @pytest.mark.parametrize(
        "hostname",
        [
            "1.1",
            "134744072",
            "127.1.example.com",
            "127.1x",
            "256.1.1.1",
            "0x100000000",
            "09.1",
            "%38%2e%38%2e%38%2e%38",
        ],
    )
    def test_non_loopback_or_malformed_numeric_hosts_are_not_misclassified(self, hostname):
        assert not is_loopback_hostname(hostname)

    def test_private_package_and_remote_urls_remain_allowed(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["transport"] = {
            "type": "streamable-http",
            "url": "http://localhost:3000/mcp",
        }
        data["remotes"][0]["url"] = "https://10.0.0.1/mcp"
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize(
        ("url", "invalid"),
        [
            (None, False),
            ("", False),
            ("https://example.com/mcp", True),
            (42, True),
            (False, True),
            ([], True),
            ({}, True),
        ],
    )
    def test_stdio_transport_url_must_be_null_or_empty(self, tmp_path, url, invalid):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["transport"]["url"] = url
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        if invalid:
            assert any("stdio" in message for message in messages_lower(findings))
        else:
            assert findings == []

    @pytest.mark.parametrize("version", sorted(MCP_REGISTRY_SCHEMA_VERSIONS))
    def test_supported_repository_shape_is_checked_for_every_schema(self, tmp_path, version):
        repo = copy_fixture(f"mcp-registry/schema-versions/{version}", tmp_path)
        path, data = _load_server(repo)
        data["repository"] = {
            "source": "github",
            "url": "http://www.github.com/example/weather.git/",
        }
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize(
        ("source", "url"),
        [
            ("github", "https://gitlab.com/example/weather"),
            ("gitlab", "https://github.com/example/weather"),
            ("bitbucket", "https://bitbucket.org/example/weather"),
            ("gitlab", "https://gitlab.com/group/subgroup/weather"),
            ("github", "https://github.com/example/weather/issues"),
            ("github", "https://github.com/example/weather?tab=readme"),
        ],
    )
    def test_repository_source_and_url_must_match_publisher_shape(self, tmp_path, source, url):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["repository"] = {"source": source, "url": url}
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("repository.url" in message for message in messages_lower(findings))

    def test_malformed_repository_url_does_not_get_duplicate_semantic_error(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["repository"] = {"source": "github", "url": "https://["}
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "repository.url" in combined
        assert "must match its supported" not in combined

    @pytest.mark.parametrize(
        "version",
        [
            "",
            " ",
            "\t",
            "latest",
            " latest ",
            "^1.2.3",
            "~1.2.3",
            ">=1.2.3",
            "1.x",
            "1.2.*",
            "1.0 - 2.0",
            "1.2 || 1.3",
            ">=1.0.0 <2.0.0",
            "^1.0.0 || ^2.0.0",
            "*",
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

    @pytest.mark.parametrize("version", ["1.x", " latest "])
    def test_package_version_range_is_an_error(self, tmp_path, version):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["version"] = version
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].version" in message for message in messages_lower(findings))

    def test_schema_error_summary_retains_a_bounded_sample(self):
        errors = (
            ValidationError(
                "must be an object",
                validator="type",
                validator_value="object",
                path=["packages", index],
            )
            for index in range(10)
        )

        summary = schema_error_summary(errors)

        assert "$.packages[0]" in summary
        assert "$.packages[3]" in summary
        assert "$.packages[4]" not in summary
        assert "and 6 more schema errors" in summary

    @pytest.mark.parametrize(
        "version",
        [
            ">=1.0.0 <2.0.0",
            "^1.0.0 || ^2.0.0",
            "1.x || 2.x",
            "1.2.* || >=2.0.0",
            "1.0 - 2.0 || 3.0 - 4.0",
            "*",
        ],
    )
    def test_package_compound_comparator_range_is_an_error(self, tmp_path, version):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["version"] = version
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].version" in message for message in messages_lower(findings))

    @pytest.mark.parametrize("version", ["1.2", "next"])
    def test_npm_package_version_must_be_an_exact_semver(self, tmp_path, version):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["version"] = version
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].version" in message for message in messages_lower(findings))

    def test_npm_package_requires_a_version(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        del data["packages"][0]["version"]
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].version" in message for message in messages_lower(findings))

    def test_non_npm_package_may_use_a_format_specific_exact_version(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = "pypi"
        data["packages"][0]["version"] = "2026.8"
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    @pytest.mark.parametrize("version", ["", "   ", "\t"])
    @pytest.mark.parametrize("registry_type", ["pypi", "cargo", "nuget", "oci", "mcpb"])
    def test_non_npm_package_version_must_not_be_blank(self, tmp_path, registry_type, version):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = registry_type
        data["packages"][0]["version"] = version
        if registry_type == "mcpb":
            data["packages"][0]["fileSha256"] = "0" * 64
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].version" in message for message in messages_lower(findings))

    @pytest.mark.parametrize(
        ("registry_type", "version"),
        [
            ("pypi", "~=1.4"),
            ("pypi", ">=1.0,<2.0"),
            ("nuget", "[1.0,2.0)"),
            ("cargo", ">=1.0, <2.0"),
        ],
    )
    def test_registry_specific_package_ranges_are_errors(self, tmp_path, registry_type, version):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = registry_type
        data["packages"][0]["version"] = version
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("packages[0].version" in message for message in messages_lower(findings))

    def test_repeated_semantic_defects_are_aggregated_per_category(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"] = [
            {
                "registryType": "company-internal",
                "identifier": f"weather-{index}",
                "version": "1.x",
                "transport": {"type": "websocket"},
            }
            for index in range(50)
        ]
        data["remotes"] = [{"type": "stdio"} for _ in range(50)]
        _write_server(path, data)

        findings = _for_rule(lint_rules(repo, VALID_RULE), VALID_RULE)

        assert len(findings) == 4
        assert all("and 46 more" in finding.message for finding in findings)

    def test_non_semver_label_containing_x_is_not_misread_as_a_range(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["version"] = "release.x"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert not any("exact release" in message for message in messages_lower(findings))

    def test_x_in_semver_prerelease_is_not_misread_as_a_wildcard(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["version"] = "1.2.3-next"
        data["packages"][0]["version"] = "1.2.3-next"
        _write_server(path, data)

        assert lint_rules(repo, VALID_RULE) == []

    def test_wildcard_core_with_prerelease_remains_a_range(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["version"] = "1.2.x-next"
        data["packages"][0]["version"] = "1.2.x-next"
        _write_server(path, data)

        findings = lint_rules(repo, VALID_RULE)

        assert any("exact release" in message for message in messages_lower(findings))


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

    @pytest.mark.parametrize("version", ["${VERSION}", "{{VERSION}}", "<<Version>>"])
    def test_release_source_placeholder_is_quiet(self, tmp_path, version):
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
    def test_release_source_server_name_placeholder_skips_local_match(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["name"] = "${NAME}"
        _write_server(path, data)

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    def test_matching_adjacent_package_passes(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)

        assert lint_rules(repo, NPM_NAME_RULE) == []

    def test_matching_workspace_package_passes(self, tmp_path):
        repo = copy_fixture("mcp-registry/monorepo", tmp_path)

        assert lint_rules(repo, NPM_NAME_RULE) == []

    def test_bare_github_repository_shortcut_matches_nearest_package(self, tmp_path):
        repo = copy_fixture("mcp-registry/chrome-layout", tmp_path)

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == repo / "package.json"

    def test_github_repository_identity_is_case_insensitive(self, tmp_path):
        repo = copy_fixture("mcp-registry/xactions-layout", tmp_path)

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == repo / "package.json"

    @pytest.mark.parametrize(
        "repository",
        ["packages/local/copy", "owner/repository/extra", "../owner/repository"],
    )
    def test_local_or_multisegment_repository_strings_are_not_github_shortcuts(
        self, tmp_path, repository
    ):
        repo = copy_fixture("mcp-registry/chrome-layout", tmp_path)
        package_path = repo / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["repository"] = repository
        package_path.write_text(json.dumps(package), encoding="utf-8")

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    def test_same_coordinates_outside_package_scope_are_ignored(self, tmp_path):
        repo = copy_fixture("mcp-registry/locality", tmp_path)

        assert lint_rules(repo, NPM_NAME_RULE) == []

    def test_repository_subfolder_describes_source_not_package_location(self, tmp_path):
        repo = copy_fixture("mcp-registry/firebase-layout", tmp_path)
        package_path = repo / "package.json"

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == package_path

    def test_repository_subfolder_does_not_veto_unique_package_fallback(self, tmp_path):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        server_path, server = _load_server(repo)
        server["repository"]["subfolder"] = "src/weather-server"
        _write_server(server_path, server)

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == repo / "packages" / "weather" / "package.json"

    def test_nearest_exact_package_honors_its_declared_directory(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        package_path = repo / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package.pop("mcpName")
        package["repository"] = {
            "url": "https://github.com/example/weather",
            "directory": "packages/actual",
        }
        package_path.write_text(json.dumps(package), encoding="utf-8")

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    def test_package_directory_selects_nested_package_across_publishable_root(self, tmp_path):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        (repo / "package.json").write_text(
            json.dumps({"name": "other-package", "version": "1.0.0"}), encoding="utf-8"
        )
        package_path = repo / "packages" / "weather" / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["repository"] = {
            "url": "https://github.com/example/weather.git",
            "directory": "packages/weather",
        }
        package_path.write_text(json.dumps(package), encoding="utf-8")

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == package_path

    def test_two_sided_repository_location_selects_nested_package(self, tmp_path):
        package_dir = tmp_path / "packages" / "soma-rmcp"
        package_dir.mkdir(parents=True)
        package = {
            "name": "@dinglebear/soma",
            "version": "0.10.0",
            "repository": {
                "url": "git+https://github.com/dinglebear-ai/soma.git",
                "directory": "packages/soma-rmcp",
            },
        }
        package_path = package_dir / "package.json"
        package_path.write_text(json.dumps(package), encoding="utf-8")
        unrelated = tmp_path / "examples" / "copy"
        unrelated.mkdir(parents=True)
        (unrelated / "package.json").write_text(
            json.dumps({"name": "@dinglebear/soma", "version": "0.10.0"}),
            encoding="utf-8",
        )
        server = {
            "$schema": MCP_REGISTRY_SCHEMA_ID,
            "name": "ai.dinglebear/soma",
            "description": "A server published from a self-described workspace package.",
            "version": "0.10.0",
            "repository": {
                "url": "https://github.com/dinglebear-ai/soma",
                "source": "github",
            },
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@dinglebear/soma",
                    "version": "0.10.0",
                    "transport": {"type": "stdio"},
                }
            ],
        }
        _write_server(tmp_path / "server.json", server)

        findings = _for_rule(lint_rules(tmp_path, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == package_path

    def test_unique_exact_coordinate_selects_nested_package_without_directory_metadata(
        self, tmp_path
    ):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        package_path = repo / "packages" / "weather" / "package.json"

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == package_path
        assert "mcpname" in findings[0].message.lower()

    def test_unique_exact_coordinate_crosses_private_root_workspace(self, tmp_path):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        (repo / "package.json").write_text(
            json.dumps({"name": "private-workspace", "version": "0.0.0", "private": True}),
            encoding="utf-8",
        )

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == repo / "packages" / "weather" / "package.json"

    def test_unique_exact_coordinate_does_not_cross_publishable_root_package(self, tmp_path):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        (repo / "package.json").write_text(
            json.dumps({"name": "other-package", "version": "1.0.0"}), encoding="utf-8"
        )

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    def test_unique_exact_coordinate_does_not_cross_nested_private_package(self, tmp_path):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        (repo / "package.json").write_text(
            json.dumps({"name": "private-workspace", "version": "0.0.0", "private": True}),
            encoding="utf-8",
        )
        (repo / "packages" / "package.json").write_text(
            json.dumps({"name": "private-example", "version": "0.0.0", "private": True}),
            encoding="utf-8",
        )

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    def test_unique_exact_coordinate_requires_same_repository(self, tmp_path):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        package_path = repo / "packages" / "weather" / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["repository"] = "github:someone-else/weather"
        package_path.write_text(json.dumps(package), encoding="utf-8")

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    @pytest.mark.parametrize(
        ("server_url", "package_repository"),
        [
            ("https://www.github.com/example/weather", "github:example/weather"),
            ("https://gitlab.com/example/weather", "gitlab:example/weather"),
        ],
    )
    def test_repository_shortcuts_match_canonical_host(
        self, tmp_path, server_url, package_repository
    ):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        server_path, server = _load_server(repo)
        server["repository"]["url"] = server_url
        _write_server(server_path, server)
        package_path = repo / "packages" / "weather" / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["repository"] = package_repository
        package_path.write_text(json.dumps(package), encoding="utf-8")

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == package_path

    def test_self_hosted_repository_paths_remain_case_sensitive(self, tmp_path):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        server_path, server = _load_server(repo)
        server["repository"]["url"] = "https://git.example.test/Owner/Weather"
        _write_server(server_path, server)
        package_path = repo / "packages" / "weather" / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["repository"] = "https://git.example.test/owner/weather"
        package_path.write_text(json.dumps(package), encoding="utf-8")

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    def test_declared_package_directory_must_match_unique_candidate_path(self, tmp_path):
        repo = copy_fixture("mcp-registry/root-server-nested-package", tmp_path)
        package_path = repo / "packages" / "weather" / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["repository"] = {
            "url": "git+https://github.com/example/weather.git",
            "directory": "packages/somewhere-else",
        }
        package_path.write_text(json.dumps(package), encoding="utf-8")

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    def test_ambiguous_corroborated_packages_are_ignored(self, tmp_path):
        repository_url = "https://github.com/example/publisher"
        for directory in ("packages/one", "packages/two"):
            package_dir = tmp_path / directory
            package_dir.mkdir(parents=True)
            package = {
                "name": "@example/server",
                "version": "1.0.0",
                "repository": {"url": repository_url, "directory": directory},
            }
            (package_dir / "package.json").write_text(json.dumps(package), encoding="utf-8")
        server = {
            "$schema": MCP_REGISTRY_SCHEMA_ID,
            "name": "com.example/server",
            "description": "Ambiguous source packages for one published coordinate.",
            "version": "1.0.0",
            "repository": {"url": repository_url, "source": "github"},
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@example/server",
                    "version": "1.0.0",
                    "transport": {"type": "stdio"},
                }
            ],
        }
        _write_server(tmp_path / "server.json", server)

        assert lint_rules(tmp_path, NPM_NAME_RULE) == []

    def test_different_local_package_version_is_not_treated_as_referenced_release(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        package_path = repo / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["version"] = "2.0.0"
        package.pop("mcpName")
        package_path.write_text(json.dumps(package), encoding="utf-8")

        assert lint_rules(repo, NPM_NAME_RULE) == []

    def test_versionless_reference_is_reported_by_schema_dependency(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        del data["packages"][0]["version"]
        _write_server(path, data)
        package_path = repo / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package.pop("mcpName")
        package_path.write_text(json.dumps(package), encoding="utf-8")

        findings = lint_rules(repo, NPM_NAME_RULE)

        assert _for_rule(findings, NPM_NAME_RULE) == []
        assert any("packages[0].version" in message for message in messages_lower(findings))

    def test_contained_symlinked_nearest_package_is_checked(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        package_path = repo / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package.pop("mcpName")
        metadata = repo / "metadata"
        metadata.mkdir()
        target = metadata / "npm-manifest.json"
        target.write_text(json.dumps(package), encoding="utf-8")
        package_path.unlink()
        package_path.symlink_to(target.relative_to(repo))

        findings = _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE)

        assert len(findings) == 1
        assert findings[0].file_path == package_path

    def test_symlinked_package_outside_repository_is_ignored(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        package_path = repo / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package.pop("mcpName")
        external = tmp_path / "external" / "package.json"
        external.parent.mkdir()
        external.write_text(json.dumps(package), encoding="utf-8")
        package_path.unlink()
        package_path.symlink_to(external)

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    def test_shared_package_is_checked_for_each_server_identity(self, tmp_path):
        package = {
            "name": "@example/weather-mcp",
            "version": "1.0.0",
            "mcpName": "com.example/first",
            "repository": "github:example/weather-mcp",
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

    def test_invalid_adjacent_package_without_identity_is_ignored(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        package_path = repo / "package.json"
        package_path.write_text('{"name": ', encoding="utf-8")

        assert lint_rules(repo, NPM_NAME_RULE) == []

    def test_non_object_adjacent_package_without_identity_is_ignored(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        package_path = repo / "package.json"
        package_path.write_text("[]", encoding="utf-8")

        assert lint_rules(repo, NPM_NAME_RULE) == []

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
                    "version": "1.0.0",
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

    def test_non_npm_server_does_not_build_package_candidates(self, tmp_path, monkeypatch):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["registryType"] = "pypi"
        _write_server(path, data)

        def unexpected_index(_context):
            pytest.fail("non-npm metadata must not build the package.json index")

        monkeypatch.setattr(
            McpRegistryNpmNameMatchRule,
            "_package_candidates",
            staticmethod(unexpected_index),
        )

        assert _for_rule(lint_rules(repo, NPM_NAME_RULE), NPM_NAME_RULE) == []

    @pytest.mark.parametrize("invalid_version", [None, 7])
    def test_invalid_declared_version_skips_ownership_matching(self, tmp_path, invalid_version):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path, data = _load_server(repo)
        data["packages"][0]["version"] = invalid_version
        _write_server(path, data)
        package_path = repo / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package.pop("mcpName")
        package_path.write_text(json.dumps(package), encoding="utf-8")

        findings = lint_rules(repo, NPM_NAME_RULE)

        assert _for_rule(findings, NPM_NAME_RULE) == []
