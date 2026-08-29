"""MCP Registry repository detection and lint-tree routing."""

import json

from skillsaw.blocks import ContentBlock, McpRegistryServerBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formats.mcp_registry import (
    MCP_REGISTRY_SCHEMA_ID,
    MCP_REGISTRY_SCHEMA_VERSION,
    load_mcp_registry_schema,
    mcp_registry_schema_version,
)

from ._helpers import copy_fixture


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

    def test_unrelated_server_json_is_ignored(self, tmp_path):
        repo = copy_fixture("mcp-registry/unrelated", tmp_path)
        context = RepositoryContext(repo)

        assert RepositoryType.MCP_REGISTRY not in context.repo_types
        assert context.mcp_registry_server_paths() == []
        assert context.lint_tree.find(McpRegistryServerBlock) == []

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


class TestMcpRegistrySchemaBundle:
    def test_schema_version_parser_is_exact(self):
        assert mcp_registry_schema_version(MCP_REGISTRY_SCHEMA_ID) == (MCP_REGISTRY_SCHEMA_VERSION)
        assert mcp_registry_schema_version("http://example.com/server.schema.json") is None
        assert mcp_registry_schema_version(42) is None

    def test_bundled_schema_is_the_pinned_release(self):
        schema = load_mcp_registry_schema()

        assert schema["title"] == "server.json defining a Model Context Protocol (MCP) server"
        server = schema["definitions"]["ServerDetail"]
        assert server["required"] == ["name", "description", "version"]
