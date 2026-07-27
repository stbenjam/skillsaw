"""``skillsaw docs`` extraction and rendering for Codex content."""

import json

import pytest

from skillsaw.blocks import PluginRuleBlock
from skillsaw.docs.extractor import extract_docs
from skillsaw.docs.html_renderer import render_html
from skillsaw.docs.markdown_renderer import render_markdown
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import CodexPluginNode

from ._helpers import _write_plugin, _codex_plugin_repo, _codex_marketplace_repo


class TestCodexOnlyPluginDocs:
    def test_docs_describe_a_codex_only_plugin(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "documented",
                "version": "2.1.0",
                "description": "Does a documented thing.",
                "author": {"name": "Someone"},
                "license": "MIT",
                "interface": {"displayName": "Documented Plugin"},
                "mcpServers": {"local": {"command": "node", "args": ["s.js"]}},
                "hooks": {
                    "hooks": {
                        "SessionStart": [{"hooks": [{"type": "command", "command": "echo ready"}]}]
                    }
                },
            },
        )
        skill = repo / "skills" / "capture"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: capture\ndescription: Capture a note\n---\n\n# Capture\n",
            encoding="utf-8",
        )

        docs = extract_docs(RepositoryContext(repo))

        assert len(docs.plugins) == 1
        plugin = docs.plugins[0]
        assert plugin.name == "documented"
        assert plugin.version == "2.1.0"
        assert plugin.description == "Does a documented thing."
        assert plugin.display_name == "Documented Plugin"
        assert plugin.license == "MIT"
        assert [s.name for s in plugin.skills] == ["capture"]
        assert [h.event_type for h in plugin.hooks] == ["SessionStart"]
        assert [s.name for s in plugin.mcp_servers] == ["local"]

    def test_a_dual_ecosystem_plugin_is_documented_once(self, tmp_path):
        repo = tmp_path / "dual"
        plugin = repo / "plugins" / "both"
        _write_plugin(plugin, {"name": "both", "version": "1.0.0"})
        (plugin / ".claude-plugin").mkdir()
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "both", "version": "1.0.0", "description": "Both."}),
            encoding="utf-8",
        )
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text("Run the thing.\n", encoding="utf-8")

        docs = extract_docs(RepositoryContext(repo))
        assert [p.name for p in docs.plugins] == ["both"]

    def test_a_manifestless_directory_is_not_documented(self, tmp_path):
        repo = tmp_path / "hollow"
        (repo / ".codex-plugin").mkdir(parents=True)

        assert extract_docs(RepositoryContext(repo)).plugins == []


class TestCodexMarketplaceDocs:
    def test_every_plugin_in_the_catalog_is_rendered(self, tmp_path):
        """The single-page renderer shows plugins[0] and drops the rest."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "example-catalog",
                "plugins": [
                    {
                        "name": name,
                        "source": {"source": "local", "path": f"./plugins/{name}"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                    for name in ("alpha", "beta", "gamma")
                ],
            },
        )
        for name in ("alpha", "beta", "gamma"):
            _write_plugin(
                repo / "plugins" / name,
                {
                    "name": name,
                    "version": "1.0.0",
                    "description": f"The {name} plugin.",
                },
            )

        docs = extract_docs(RepositoryContext(repo))
        assert docs.marketplace is not None
        assert docs.marketplace.name == "example-catalog"
        assert {p.name for p in docs.plugins} == {"alpha", "beta", "gamma"}

        pages = render_markdown(docs)
        rendered = "\n".join(pages.values())
        for name in ("alpha", "beta", "gamma"):
            assert name in rendered, f"{name} missing from rendered docs"

    def test_mcp_servers_report_their_real_source(self, tmp_path):
        """An inline or custom-path server is attributed to the file that
        actually declares it, never to a `.mcp.json` that need not exist."""
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": []})
        plugin = _write_plugin(
            repo / "plugins" / "sources",
            {
                "name": "sources",
                "version": "1.0.0",
                "description": "x",
                "mcpServers": [
                    "./servers.json",
                    {"inline-one": {"command": "node"}},
                ],
            },
        )
        (plugin / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"from-default": {"command": "node"}}}),
            encoding="utf-8",
        )
        (plugin / "servers.json").write_text(
            json.dumps({"mcpServers": {"from-declared": {"command": "node"}}}),
            encoding="utf-8",
        )

        doc = next(p for p in extract_docs(RepositoryContext(repo)).plugins if p.name == "sources")
        sources = {s.name: s.source_file for s in doc.mcp_servers}

        assert sources == {
            "from-default": ".mcp.json",
            "from-declared": "servers.json",
            "inline-one": "plugin.json",
        }


class TestGeneratedDocsFidelity:
    def test_the_interface_category_is_used(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "categorised",
                "version": "1.0.0",
                "description": "x",
                "interface": {"displayName": "Categorised", "category": "Productivity"},
            },
        )
        assert extract_docs(RepositoryContext(repo)).plugins[0].category == "Productivity"

    def test_colliding_sanitized_names_get_distinct_pages(self, tmp_path):
        """ "a/b" and "a:b" both sanitize to "a-b" — one page would win."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": n,
                        "source": {
                            "source": "url",
                            "url": f"https://example.com/{i}.git",
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                    for i, n in enumerate(["a/b", "a:b", "a-b"])
                ],
            },
        )
        pages = render_markdown(extract_docs(RepositoryContext(repo)))
        plugin_pages = [k for k in pages if k != "README.md"]

        assert len(plugin_pages) == 3, f"pages collided: {sorted(pages)}"

    def test_remote_entries_appear_in_the_catalog(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "remote-one",
                        "source": {"source": "npm", "package": "@x/y"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        docs = extract_docs(RepositoryContext(repo))
        assert [p.name for p in docs.marketplace.plugins] == ["remote-one"]

    def test_a_catalog_renders_fully_when_another_type_is_primary(self, tmp_path):
        """APM outranks codex-marketplace for the primary type slot."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": name,
                        "source": {"source": "local", "path": f"./plugins/{name}"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                    for name in ("alpha", "beta")
                ],
            },
        )
        for name in ("alpha", "beta"):
            _write_plugin(repo / "plugins" / name, {"name": name, "version": "1.0.0"})
        (repo / ".apm").mkdir()
        (repo / "apm.yml").write_text("name: thing\n", encoding="utf-8")

        docs = extract_docs(RepositoryContext(repo))
        rendered = "\n".join(render_markdown(docs).values())
        assert "alpha" in rendered and "beta" in rendered

    def test_a_malformed_skill_description_cannot_break_docs(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path, {"name": "skills", "version": "1.0.0", "description": "x"}
        )
        skill = repo / "skills" / "broken"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: broken\ndescription:\n  nested: value\n---\n\n# Broken\n",
            encoding="utf-8",
        )

        docs = extract_docs(RepositoryContext(repo))
        assert docs.plugins[0].skills[0].description == ""
        assert render_markdown(docs)
        assert render_html(docs)

    def test_remote_metadata_is_escaped_for_markdown_tables(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "remote",
                        "description": "Works on Linux | macOS\nand Windows",
                        "version": "1|2",
                        "source": {"source": "npm", "package": "@x/y"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )

        readme = render_markdown(extract_docs(RepositoryContext(repo)))["README.md"]
        assert "Works on Linux \\| macOS and Windows" in readme
        assert "1\\|2" in readme


class TestCatalogAggregation:
    def test_remote_entries_from_every_catalog_are_listed(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "primary",
                "plugins": [
                    {
                        "name": "from-primary",
                        "source": {"source": "npm", "package": "@x/a"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        (repo / ".agents" / "plugins" / "api_marketplace.json").write_text(
            json.dumps(
                {
                    "name": "secondary",
                    "plugins": [
                        {
                            "name": "from-sibling",
                            "source": {"source": "npm", "package": "@x/b"},
                            "policy": {
                                "installation": "AVAILABLE",
                                "authentication": "ON_USE",
                            },
                            "category": "Productivity",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        docs = extract_docs(RepositoryContext(repo))
        assert {p.name for p in docs.marketplace.plugins} == {
            "from-primary",
            "from-sibling",
        }
        assert docs.marketplace.name == "primary", "the first catalog names the marketplace"


class TestCodexOnlyPluginNodeDocs:
    def test_codex_metadata_is_read_when_a_plugin_node_exists_without_a_manifest(self, tmp_path):
        """`commands/` alone creates a PluginNode — that is not a Claude plugin."""
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": []})
        plugin = _write_plugin(
            repo / "plugins" / "hybrid",
            {
                "name": "hybrid",
                "version": "3.2.1",
                "description": "Has commands but no Claude manifest.",
                "license": "MIT",
            },
        )
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text("Run it.\n", encoding="utf-8")

        doc = next(p for p in extract_docs(RepositoryContext(repo)).plugins if p.name == "hybrid")
        assert doc.version == "3.2.1"
        assert doc.description == "Has commands but no Claude manifest."
        assert doc.license == "MIT"


class TestMarketplaceDocMerging:
    def test_codex_remotes_survive_a_claude_marketplace(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "codex-cat",
                "plugins": [
                    {
                        "name": "remote-only",
                        "source": {"source": "npm", "package": "@x/y"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        (repo / ".claude-plugin").mkdir()
        (repo / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"name": "claude-cat", "owner": {"name": "someone"}, "plugins": []}),
            encoding="utf-8",
        )

        docs = extract_docs(RepositoryContext(repo))
        assert docs.marketplace.name == "claude-cat"
        assert "remote-only" in {p.name for p in docs.marketplace.plugins}

    def test_a_malformed_local_entry_is_not_published_as_remote(self, tmp_path):
        """`{"source": "local"}` with no path is broken, not remote."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "ghost",
                        "source": {"source": "local"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        docs = extract_docs(RepositoryContext(repo))
        assert "ghost" not in {p.name for p in docs.marketplace.plugins}

    def test_mixed_catalog_filters_unregistered_codex_only_plugins(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "codex-cat",
                "plugins": [
                    {
                        "name": "listed",
                        "source": {"source": "local", "path": "./plugins/listed"},
                        "category": "Productivity",
                    }
                ],
            },
        )
        _write_plugin(repo / "plugins" / "listed", {"name": "listed", "version": "1.0.0"})
        _write_plugin(repo / "plugins" / "stray", {"name": "stray", "version": "1.0.0"})
        (repo / ".claude-plugin").mkdir()
        (repo / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"name": "claude-cat", "owner": {"name": "someone"}, "plugins": []}),
            encoding="utf-8",
        )

        docs = extract_docs(RepositoryContext(repo))
        published = {p.name for p in docs.marketplace.plugins}
        assert published == {"listed"}


class TestHtmlMarketplaceMode:
    def test_a_codex_catalog_renders_as_a_marketplace_under_another_primary_type(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": n,
                        "source": {"source": "local", "path": f"./plugins/{n}"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                    for n in ("alpha", "beta")
                ],
            },
        )
        for n in ("alpha", "beta"):
            _write_plugin(repo / "plugins" / n, {"name": n, "version": "1.0.0"})
        (repo / ".apm").mkdir()
        (repo / "apm.yml").write_text("name: thing\n", encoding="utf-8")

        pages = render_html(extract_docs(RepositoryContext(repo)))
        html = "\n".join(pages.values())
        assert "var IS_MARKETPLACE = true" in html


class TestCodexOnlyPluginConfigDocs:
    def test_hooks_and_mcp_survive_a_legacy_plugin_node(self, tmp_path):
        """Legacy discovery claims hooks.json/.mcp.json first for any plugin
        shipping commands/, and the tree's `seen` set keeps them off the
        Codex node."""
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": []})
        plugin = _write_plugin(
            repo / "plugins" / "hybrid",
            {"name": "hybrid", "version": "1.0.0", "description": "x"},
        )
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text("Run it.\n", encoding="utf-8")
        (plugin / "hooks").mkdir()
        (plugin / "hooks" / "hooks.json").write_text(
            json.dumps(
                {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo"}]}]}}
            ),
            encoding="utf-8",
        )
        (plugin / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"local": {"command": "node"}}}), encoding="utf-8"
        )

        doc = next(p for p in extract_docs(RepositoryContext(repo)).plugins if p.name == "hybrid")
        assert [h.event_type for h in doc.hooks] == ["SessionStart"]
        assert [m.name for m in doc.mcp_servers] == ["local"]


class TestDocsBlockDeduplication:
    def test_inline_config_is_not_listed_twice(self, tmp_path):
        """The legacy PluginNode has the Codex node as a descendant, so
        searching both must not list the Codex node's blocks twice."""
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": []})
        plugin = _write_plugin(
            repo / "plugins" / "hybrid",
            {
                "name": "hybrid",
                "version": "1.0.0",
                "description": "x",
                "mcpServers": {"only": {"command": "node"}},
            },
        )
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text("Run it.\n", encoding="utf-8")

        doc = next(p for p in extract_docs(RepositoryContext(repo)).plugins if p.name == "hybrid")
        assert [m.name for m in doc.mcp_servers] == ["only"]


class TestCatalogMembership:
    """A catalog's ``plugins`` array defines its membership, not whatever
    discovery happened to find on disk."""

    def test_a_dot_claude_directory_is_not_published_as_a_catalog_entry(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "my-catalog",
                "plugins": [
                    {
                        "name": "note-taker",
                        "source": {"source": "local", "path": "./plugins/note-taker"},
                    }
                ],
            },
        )
        _write_plugin(
            repo / "plugins" / "note-taker",
            {"name": "note-taker", "version": "1.0.0", "description": "Take notes"},
        )
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "go.md").write_text("Run it.\n", encoding="utf-8")

        docs = extract_docs(RepositoryContext(repo))
        assert [p.name for p in docs.marketplace.plugins] == ["note-taker"]

    def test_a_listings_category_reaches_the_rendered_docs(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "one",
                        "source": {"source": "local", "path": "./plugins/one"},
                        "category": "Productivity",
                    }
                ],
            },
        )
        _write_plugin(repo / "plugins" / "one", {"name": "one", "version": "1.0.0"})

        docs = extract_docs(RepositoryContext(repo))
        assert docs.marketplace.plugins[0].category == "Productivity"
        assert "Productivity" in "\n".join(render_html(docs).values())

    def test_a_manifest_category_is_not_overwritten_by_the_listing(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "one",
                        "source": {"source": "local", "path": "./plugins/one"},
                        "category": "Productivity",
                    }
                ],
            },
        )
        _write_plugin(
            repo / "plugins" / "one",
            {
                "name": "one",
                "version": "1.0.0",
                "interface": {"category": "Developer Tools"},
            },
        )

        docs = extract_docs(RepositoryContext(repo))
        assert docs.marketplace.plugins[0].category == "Developer Tools"


class TestHtmlUsesCatalogMembership:
    def test_a_remote_only_catalog_does_not_render_an_empty_grid(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "faraway",
                        "description": "Lives elsewhere",
                        "source": {
                            "source": "url",
                            "url": "https://example.com/faraway",
                        },
                    }
                ],
            },
        )
        html = "\n".join(render_html(extract_docs(RepositoryContext(repo))).values())
        assert "faraway" in html


class TestExcludedCatalogsAreNotDocumented:
    def test_an_excluded_catalog_publishes_no_pages(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "secret-catalog",
                "plugins": [
                    {
                        "name": "hidden",
                        "source": {
                            "source": "url",
                            "url": "https://example.com/hidden",
                        },
                    }
                ],
            },
        )
        context = RepositoryContext(repo, exclude_patterns=[".agents/plugins/**"])

        docs = extract_docs(context)
        assert docs.marketplace is None
        assert docs.plugins == []
        assert "secret-catalog" not in "\n".join(render_html(docs).values())


class TestAuthorOnlyMetadataSurvives:
    def test_an_author_with_no_other_metadata_reaches_the_html(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "authored",
                "version": "1.0.0",
                "description": "x",
                "author": {"name": "Ada Lovelace"},
            },
        )
        html = "\n".join(render_html(extract_docs(RepositoryContext(repo))).values())
        assert "Ada Lovelace" in html


class TestMalformedDocsInputDoesNotAbort:
    """`skillsaw docs` must tolerate anything `lint` merely reports."""

    def test_a_non_list_plugins_value_is_skipped(self, tmp_path):
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": 42})
        assert render_html(extract_docs(RepositoryContext(repo)))

    @pytest.mark.parametrize("tools", ["[Read, 42]", "[42]", "Read"])
    def test_non_string_allowed_tools_are_dropped(self, tmp_path, tools):
        repo = _codex_plugin_repo(
            tmp_path, {"name": "holder", "version": "1.0.0", "description": "x"}
        )
        skill = repo / "skills" / "worker"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: worker\ndescription: A skill with odd tools\n"
            f"allowed-tools: {tools}\n---\n\n# Worker\n",
            encoding="utf-8",
        )
        docs = extract_docs(RepositoryContext(repo))
        for plugin in docs.plugins:
            for s in plugin.skills:
                assert all(isinstance(t, str) for t in s.allowed_tools)
        assert render_markdown(docs) and render_html(docs)

    def test_a_mapping_valued_skill_name_is_serialized_as_a_string(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path, {"name": "holder", "version": "1.0.0", "description": "x"}
        )
        skill = repo / "skills" / "worker"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname:\n  a: 1\ndescription: A skill whose name is a mapping\n---\n\n# W\n",
            encoding="utf-8",
        )
        docs = extract_docs(RepositoryContext(repo))
        for plugin in docs.plugins:
            for s in plugin.skills:
                assert isinstance(s.name, str)
        assert render_html(docs)


class TestDocsRenderTotality:
    def test_docs_survive_non_scalar_prose_frontmatter(self, tmp_path):
        """A list-valued command description must not reach the Markdown
        renderer's line list, where it aborts generation with TypeError."""
        repo = tmp_path / "claude-repo"
        plugin = repo / "plugins" / "cl"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "cl", "version": "1.0.0", "description": "A plugin."}),
            encoding="utf-8",
        )
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text(
            "---\ndescription: [not, text]\n---\nBody prose.\n", encoding="utf-8"
        )
        (plugin / "agents").mkdir()
        (plugin / "agents" / "helper.md").write_text(
            "---\nname: [also, wrong]\ndescription: {nested: map}\n---\nAgent prose.\n",
            encoding="utf-8",
        )

        docs = extract_docs(RepositoryContext(repo))
        md_pages = render_markdown(docs)  # must not raise
        render_html(docs)
        joined = "\n".join(md_pages.values())
        assert "go" in joined
        assert "helper" in joined  # name fell back to the file stem


class TestNestedPluginUnderRules:
    def test_a_nested_plugins_files_are_not_claimed_by_the_root_scan(self, tmp_path):
        """A catalog-sourced plugin nested below a repo-root plugin's rules/
        keeps its own files: the root's recursive rules/**/*.md scan must
        not tag them with the outer owner (which would also poison the
        ``seen`` set and block the nested plugin's own attach), and the
        generated docs must attribute them to the nested plugin only."""
        repo = _codex_plugin_repo(
            tmp_path,
            {"name": "outer", "version": "1.0.0", "description": "The outer plugin."},
        )
        (repo / "rules").mkdir()
        (repo / "rules" / "policy.md").write_text(
            "Always follow the outer repository policy.\n", encoding="utf-8"
        )
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": "cat",
                    "plugins": [
                        {
                            "name": "inner-plugin",
                            "source": {"source": "local", "path": "./rules/nested"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        nested = _write_plugin(
            repo / "rules" / "nested",
            {"name": "inner-plugin", "version": "1.0.0", "description": "The nested plugin."},
        )
        (nested / "rules").mkdir()
        (nested / "rules" / "inner.md").write_text(
            "Always follow the inner plugin rule.\n", encoding="utf-8"
        )

        context = RepositoryContext(repo)

        # Lint tree: each rule file is owned by, and attached under, the
        # plugin that ships it.
        owners = {b.path.name: b.plugin_owner for b in context.lint_tree.find(PluginRuleBlock)}
        assert owners == {"policy.md": repo.resolve(), "inner.md": nested.resolve()}
        nested_containers = context.lint_tree.find(CodexPluginNode)
        assert [n.path for n in nested_containers] == [nested]
        assert {b.path.name for b in nested_containers[0].find(PluginRuleBlock)} == {"inner.md"}

        # Docs: no duplication, no misattribution.
        docs = extract_docs(context)
        rules_by_plugin = {p.name: [r.name for r in p.rules] for p in docs.plugins}
        assert rules_by_plugin == {"outer": ["policy"], "inner-plugin": ["inner"]}


class TestNonStringNamesDoNotCrashSorting:
    @pytest.mark.parametrize("name", [["a", "b"], 42, None, {"x": 1}])
    def test_a_non_string_plugin_name_still_renders(self, tmp_path, name):
        repo = _codex_plugin_repo(tmp_path, {"name": name, "version": "1.0.0", "description": "x"})
        skill = repo / "skills" / "s"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: s\ndescription: A skill with an ordinary name\n---\n\n# S\n",
            encoding="utf-8",
        )
        docs = extract_docs(RepositoryContext(repo))
        assert render_html(docs)
        assert render_markdown(docs)
