"""MCP Registry repository detection and lint-tree routing."""

import json
from importlib import resources

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
    def test_schema_version_parser_is_exact(self):
        assert mcp_registry_schema_version(MCP_REGISTRY_SCHEMA_ID) == (MCP_REGISTRY_SCHEMA_VERSION)
        assert mcp_registry_schema_version("http://example.com/server.schema.json") is None
        assert mcp_registry_schema_version(42) is None

    def test_bundled_schema_is_the_pinned_release(self):
        schema = load_mcp_registry_schema()

        assert schema["title"] == "server.json defining a Model Context Protocol (MCP) server"
        server = schema["definitions"]["ServerDetail"]
        assert server["required"] == ["name", "description", "version"]

    def test_upstream_mit_notice_is_bundled(self):
        notice = (
            resources.files("skillsaw.schemas.mcp_registry.v2025_12_11")
            .joinpath("LICENSE")
            .read_text(encoding="utf-8")
        )

        assert "MIT License" in notice
        assert "Copyright (c) 2025 Model Context Protocol" in notice
