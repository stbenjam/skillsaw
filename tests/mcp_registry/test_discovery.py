"""MCP Registry repository detection and lint-tree routing."""

import hashlib
import json
from importlib import resources

import pytest
from jsonschema import Draft7Validator, Draft202012Validator

from skillsaw.blocks import (
    ContentBlock,
    McpBlock,
    McpRegistryNpmPackageBlock,
    McpRegistryServerBlock,
    SettingsBlock,
)
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formats.mcp_registry import (
    MCP_REGISTRY_SCHEMA_ID,
    MCP_REGISTRY_SCHEMA_PACKAGES,
    MCP_REGISTRY_SCHEMA_PROFILES,
    MCP_REGISTRY_SCHEMA_VERSION,
    MCP_REGISTRY_SCHEMA_VERSIONS,
    load_mcp_registry_schema,
    mcp_registry_schema_id,
    mcp_registry_schema_version,
)
from skillsaw.rules.builtin.mcp_registry import _helpers as registry_helpers

from ._helpers import copy_fixture

_RELEASED_SCHEMA_SHA256 = {
    "2025-07-09": "9e349ba6b321bdf99432666f67e019b4b27e58ecc816fede4c08adc797e4f88a",
    "2025-09-16": "a5c19f122907b4e0684ca08f36b944c3d0972799bc6223d575d5677f94717b0b",
    "2025-09-29": "80fede68c01e868b7170b966f247bd32b9932c46f3fbef2e3b0d0a18996bf54f",
    "2025-10-11": "64135841ae0929143b22b70cbe0dda1483f7ee011adf9e19a3cee38392476808",
    "2025-10-17": "2cc1552fb3a00ad83d9ae4ee0445a21617098963b58e9bae7b94d680d841b4cc",
    "2025-12-11": "3fba09590c99f61735d234822279f4223fab9e300c0a81e81c91ab62a4114de0",
}


class TestMcpRegistryDetection:
    def test_canonical_schema_detects_root_document(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.MCP_REGISTRY in context.repo_types
        assert context.repo_type is RepositoryType.MCP_REGISTRY
        assert context.mcp_registry_server_paths() == [repo / "server.json"]
        blocks = context.lint_tree.find(McpRegistryServerBlock)
        assert [block.path for block in blocks] == [repo / "server.json"]
        assert all(not isinstance(block, ContentBlock) for block in blocks)
        packages = context.lint_tree.find(McpRegistryNpmPackageBlock)
        assert [block.path for block in packages] == [repo / "package.json"]

    def test_nested_workspace_document_is_detected(self, tmp_path):
        repo = copy_fixture("mcp-registry/monorepo", tmp_path)
        expected = repo / "packages" / "weather" / "server.json"
        context = RepositoryContext(repo)

        assert RepositoryType.MCP_REGISTRY in context.repo_types
        assert context.mcp_registry_server_paths() == [expected]
        assert [block.path for block in context.lint_tree.find(McpRegistryServerBlock)] == [
            expected
        ]

    def test_distinctive_shape_detects_missing_schema_for_diagnostics(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        path = repo / "server.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["$schema"]
        path.write_text(json.dumps(data), encoding="utf-8")

        context = RepositoryContext(repo)

        assert RepositoryType.MCP_REGISTRY in context.repo_types
        assert context.mcp_registry_server_paths() == [path]

    def test_initial_snake_case_shape_detects_missing_schema_for_diagnostics(self, tmp_path):
        repo = copy_fixture("mcp-registry/schema-versions/2025-07-09", tmp_path)
        path = repo / "server.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["$schema"]
        path.write_text(json.dumps(data), encoding="utf-8")

        context = RepositoryContext(repo)

        assert RepositoryType.MCP_REGISTRY in context.repo_types
        assert context.mcp_registry_server_paths() == [path]

    def test_unrelated_server_json_is_ignored(self, tmp_path):
        repo = copy_fixture("mcp-registry/unrelated", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.MCP_REGISTRY not in context.repo_types
        assert context.mcp_registry_server_paths() == []
        assert context.lint_tree.find(McpRegistryServerBlock) == []

    def test_generic_application_remotes_are_not_registry_evidence(self, tmp_path):
        (tmp_path / "server.json").write_text(
            json.dumps(
                {
                    "name": "api",
                    "description": "service",
                    "version": "1",
                    "remotes": [{"type": "git"}],
                }
            ),
            encoding="utf-8",
        )

        context = RepositoryContext(tmp_path)

        assert RepositoryType.MCP_REGISTRY not in context.repo_types
        assert context.mcp_registry_server_paths() == []

    def test_vendor_and_node_modules_documents_are_ignored(self, tmp_path):
        for parent in (tmp_path / "vendor" / "service", tmp_path / "node_modules" / "service"):
            parent.mkdir(parents=True)
            (parent / "server.json").write_text(
                json.dumps({"$schema": MCP_REGISTRY_SCHEMA_ID}),
                encoding="utf-8",
            )

        context = RepositoryContext(tmp_path)

        assert context.mcp_registry_server_paths() == []
        assert context.package_json_paths() == []

    def test_exclude_filters_document_and_refreshes_cache(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        context = RepositoryContext(repo)
        assert context.mcp_registry_server_paths()

        context.exclude_patterns = ["server.json"]
        context.apply_excludes()

        assert context.mcp_registry_server_paths() == []

    def test_forced_type_attaches_malformed_json(self, tmp_path):
        path = tmp_path / "server.json"
        path.write_text('{"name": ', encoding="utf-8")

        context = RepositoryContext(
            tmp_path,
            repo_types={RepositoryType.MCP_REGISTRY},
        )

        assert context.mcp_registry_server_paths() == [path]
        assert [block.path for block in context.lint_tree.find(McpRegistryServerBlock)] == [path]

    def test_unrelated_explicit_type_disables_registry_discovery(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)

        context = RepositoryContext(repo, repo_types={RepositoryType.PROMPTFOO})

        assert context.mcp_registry_server_paths() == []
        assert context.lint_tree.find(McpRegistryServerBlock) == []
        assert context.lint_tree.find(McpRegistryNpmPackageBlock) == []

    def test_registry_parser_roles_do_not_hide_plugin_contributors(self, tmp_path):
        repo = copy_fixture("mcp-registry/clean", tmp_path)
        context = RepositoryContext(repo)
        context.plugin_tree_contributors.append(
            (
                "test-plugin",
                lambda _context, _root: [
                    McpBlock(path=repo / "server.json"),
                    SettingsBlock(path=repo / "package.json"),
                ],
            )
        )

        assert [block.path for block in context.lint_tree.find(McpRegistryServerBlock)] == [
            repo / "server.json"
        ]
        assert [block.path for block in context.lint_tree.find(McpRegistryNpmPackageBlock)] == [
            repo / "package.json"
        ]
        assert [block.path for block in context.lint_tree.find(McpBlock)] == [repo / "server.json"]
        assert [block.path for block in context.lint_tree.find(SettingsBlock)] == [
            repo / "package.json"
        ]

    def test_escaping_server_json_symlink_is_not_detection_evidence(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "server.json").write_text(
            json.dumps({"$schema": MCP_REGISTRY_SCHEMA_ID}),
            encoding="utf-8",
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "server.json").symlink_to(outside / "server.json")

        context = RepositoryContext(repo)

        assert context.mcp_registry_server_paths() == []
        assert RepositoryType.MCP_REGISTRY not in context.repo_types
        assert context.lint_tree.find(McpRegistryServerBlock) == []

    def test_escaping_package_json_symlink_is_not_attached(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "package.json").write_text(
            json.dumps({"name": "@example/weather-mcp"}),
            encoding="utf-8",
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "server.json").write_text(
            json.dumps({"$schema": MCP_REGISTRY_SCHEMA_ID}),
            encoding="utf-8",
        )
        (repo / "package.json").symlink_to(outside / "package.json")

        context = RepositoryContext(repo)

        assert context.package_json_paths() == []
        assert context.lint_tree.find(McpRegistryNpmPackageBlock) == []


class TestMcpRegistrySchemaBundle:
    def test_all_released_server_schema_versions_are_registered(self):
        assert MCP_REGISTRY_SCHEMA_VERSIONS == frozenset(_RELEASED_SCHEMA_SHA256)

    def test_schema_version_parser_is_exact(self):
        assert mcp_registry_schema_version(MCP_REGISTRY_SCHEMA_ID) == (MCP_REGISTRY_SCHEMA_VERSION)
        assert mcp_registry_schema_version("http://example.com/server.schema.json") is None
        assert mcp_registry_schema_version(42) is None

    def test_supported_versions_select_the_latest_canonical_identifier(self):
        assert MCP_REGISTRY_SCHEMA_VERSION == max(MCP_REGISTRY_SCHEMA_VERSIONS)
        assert MCP_REGISTRY_SCHEMA_ID == mcp_registry_schema_id(MCP_REGISTRY_SCHEMA_VERSION)
        assert MCP_REGISTRY_SCHEMA_VERSION in MCP_REGISTRY_SCHEMA_VERSIONS

    def test_schema_profiles_preserve_the_field_name_transition(self):
        initial = MCP_REGISTRY_SCHEMA_PROFILES["2025-07-09"]
        camel_case = MCP_REGISTRY_SCHEMA_PROFILES["2025-09-16"]

        assert initial.registry_type_field == "registry_type"
        assert initial.file_sha256_field == "file_sha256"
        assert camel_case.registry_type_field == "registryType"
        assert camel_case.file_sha256_field == "fileSha256"

    def test_bundled_schema_is_the_pinned_release(self):
        schema = load_mcp_registry_schema(MCP_REGISTRY_SCHEMA_VERSION)

        assert schema["title"] == "server.json defining a Model Context Protocol (MCP) server"
        server = schema["definitions"]["ServerDetail"]
        assert server["required"] == ["name", "description", "version"]

    @pytest.mark.parametrize(
        ("version", "package"),
        sorted(MCP_REGISTRY_SCHEMA_PACKAGES.items()),
    )
    def test_registered_bundle_is_complete_and_offline(self, version, package):
        root = resources.files(package)
        schema = load_mcp_registry_schema(version)
        schema_bytes = root.joinpath("server.schema.json").read_bytes()

        assert schema["$id"] == mcp_registry_schema_id(version)
        assert hashlib.sha256(schema_bytes).hexdigest() == _RELEASED_SCHEMA_SHA256[version]
        assert root.joinpath("server.schema.json").is_file()
        assert root.joinpath("LICENSE").is_file()
        assert root.joinpath("SCHEMA-SOURCE.md").is_file()

        pending = [schema]
        references = []
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
                    reference = value.get(keyword)
                    if isinstance(reference, str):
                        references.append(reference)
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        assert all(reference.startswith("#") for reference in references)

    def test_validator_cache_is_version_and_dialect_aware(self, monkeypatch):
        schemas = {
            "draft7": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
            },
            "draft2020": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
            },
            "unknown": {
                "$schema": "https://example.invalid/unknown-dialect",
                "type": "object",
            },
        }
        monkeypatch.setattr(registry_helpers, "load_mcp_registry_schema", schemas.__getitem__)
        registry_helpers.registry_validator.cache_clear()
        try:
            draft7 = registry_helpers.registry_validator("draft7")
            draft2020 = registry_helpers.registry_validator("draft2020")

            assert isinstance(draft7, Draft7Validator)
            assert isinstance(draft2020, Draft202012Validator)
            assert registry_helpers.registry_validator("draft7") is draft7
            assert draft2020 is not draft7
            with pytest.raises(RuntimeError, match="unsupported JSON Schema dialect"):
                registry_helpers.registry_validator("unknown")
        finally:
            registry_helpers.registry_validator.cache_clear()

    def test_unbundled_schema_version_is_rejected(self):
        with pytest.raises(ValueError, match="2025-07-09.*2025-12-11"):
            load_mcp_registry_schema("2099-01-01")

    def test_upstream_mit_notice_is_bundled(self):
        notice = (
            resources.files("skillsaw.schemas.mcp_registry.v2025_12_11")
            .joinpath("LICENSE")
            .read_text(encoding="utf-8")
        )

        assert "MIT License" in notice
        assert "Copyright (c) 2025 Model Context Protocol" in notice
