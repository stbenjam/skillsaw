"""Tests for the docs subcommand: extractor, HTML renderer, markdown renderer, and CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.docs.extractor import extract_docs
from skillsaw.docs.html_renderer import render_html, COLOR_THEMES
from skillsaw.docs.markdown_renderer import render_markdown
from skillsaw.docs.models import DocsOutput, MarketplaceDoc, PluginDoc

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dot_claude_repo(temp_dir):
    """Create a .claude directory repo with commands, skills, agents, hooks, rules."""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()

    # Commands
    commands_dir = claude_dir / "commands"
    commands_dir.mkdir()
    (commands_dir / "greet.md").write_text(
        "---\ndescription: Say hello\n---\n\n"
        "## Name\nmy-tool:greet\n\n"
        "## Synopsis\n```\n/my-tool:greet [name]\n```\n\n"
        "## Description\nGreets the user.\n\n"
        "## Implementation\nPrint hello.\n"
    )

    # Skills
    skills_dir = claude_dir / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "review"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Code review skill\n"
        "license: MIT\ncompatibility: Claude 3.5+\n"
        "allowed-tools:\n  - code-review:pr\n---\n\n"
        "# Review Skill\n\nReviews code.\n"
    )

    # Agents
    agents_dir = claude_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "helper.md").write_text(
        "---\nname: helper\ndescription: A helpful agent\n---\n\nDoes helpful things.\n"
    )

    # Hooks
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir()
    hooks_data = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Write|Edit",
                    "hooks": [{"type": "command", "command": "echo done"}],
                }
            ]
        }
    }
    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_data))

    # Rules
    rules_dir = claude_dir / "rules"
    rules_dir.mkdir()
    (rules_dir / "style.md").write_text("---\npaths:\n  - src/**/*.py\n---\n\nFollow PEP 8.\n")

    return temp_dir


# ---------------------------------------------------------------------------
# Extractor tests
# ---------------------------------------------------------------------------


class TestExtractor:
    def test_extract_single_plugin(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        assert docs.repo_type == RepositoryType.SINGLE_PLUGIN
        assert len(docs.plugins) == 1

        plugin = docs.plugins[0]
        assert plugin.name == "test-plugin"
        assert plugin.description == "A test plugin"
        assert plugin.version == "1.0.0"
        assert len(plugin.commands) == 1
        assert plugin.commands[0].name == "test-command"
        assert plugin.commands[0].description == "Runs a test workflow and reports the result"
        assert plugin.commands[0].full_name == "test-plugin:test-command"
        assert "test-plugin:test-command" in plugin.commands[0].synopsis
        assert plugin.has_readme is True

    def test_extract_marketplace(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        assert docs.repo_type == RepositoryType.MARKETPLACE
        assert docs.marketplace is not None
        assert docs.marketplace.name == "test-marketplace"
        assert len(docs.marketplace.plugins) == 2

        names = {p.name for p in docs.marketplace.plugins}
        assert names == {"plugin-one", "plugin-two"}

        for plugin in docs.marketplace.plugins:
            assert len(plugin.commands) == 1

    def test_extract_dot_claude(self, dot_claude_repo):
        ctx = RepositoryContext(dot_claude_repo)
        docs = extract_docs(ctx)
        assert docs.repo_type == RepositoryType.DOT_CLAUDE
        assert len(docs.plugins) == 1

        plugin = docs.plugins[0]
        assert len(plugin.commands) == 1
        assert plugin.commands[0].name == "greet"
        assert plugin.commands[0].description == "Say hello"

        assert len(plugin.skills) == 1
        assert plugin.skills[0].name == "review"
        assert plugin.skills[0].license == "MIT"
        assert plugin.skills[0].allowed_tools == ["code-review:pr"]

        assert len(plugin.agents) == 1
        assert plugin.agents[0].name == "helper"

        assert len(plugin.hooks) == 1
        assert plugin.hooks[0].event_type == "PostToolUse"
        assert len(plugin.hooks[0].entries) == 1

        assert len(plugin.rules) == 1
        assert plugin.rules[0].name == "style"
        assert plugin.rules[0].globs == ["src/**/*.py"]

    def test_extract_flat_marketplace(self, flat_structure_marketplace):
        ctx = RepositoryContext(flat_structure_marketplace)
        docs = extract_docs(ctx)
        assert docs.repo_type == RepositoryType.MARKETPLACE
        assert docs.marketplace is not None
        assert len(docs.marketplace.plugins) == 1
        plugin = docs.marketplace.plugins[0]
        assert plugin.name == "flat-plugin"
        assert len(plugin.commands) == 1
        assert len(plugin.skills) == 1

    def test_extract_numeric_version_float(self, temp_dir):
        """Float version in plugin.json (e.g. 0.7) must not crash the extractor."""
        plugin_dir = temp_dir / "float-ver"
        plugin_dir.mkdir()
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(
            json.dumps({"name": "float-ver", "description": "d", "version": 0.7})
        )

        ctx = RepositoryContext(plugin_dir)
        docs = extract_docs(ctx)
        assert len(docs.plugins) == 1
        plugin = docs.plugins[0]
        assert isinstance(plugin.version, str)
        assert plugin.version == "0.7"

    def test_extract_numeric_version_int(self, temp_dir):
        """Integer version in plugin.json (e.g. 1) must not crash the extractor."""
        plugin_dir = temp_dir / "int-ver"
        plugin_dir.mkdir()
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(
            json.dumps({"name": "int-ver", "description": "d", "version": 1})
        )

        ctx = RepositoryContext(plugin_dir)
        docs = extract_docs(ctx)
        assert len(docs.plugins) == 1
        plugin = docs.plugins[0]
        assert isinstance(plugin.version, str)
        assert plugin.version == "1"

    def test_extract_null_version(self, temp_dir):
        """Explicit null version in plugin.json must produce empty string, not 'None'."""
        plugin_dir = temp_dir / "null-ver"
        plugin_dir.mkdir()
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(
            json.dumps({"name": "null-ver", "description": "d", "version": None})
        )

        ctx = RepositoryContext(plugin_dir)
        docs = extract_docs(ctx)
        assert len(docs.plugins) == 1
        plugin = docs.plugins[0]
        assert isinstance(plugin.version, str)
        assert plugin.version == ""

    def test_render_numeric_plugin_name_does_not_crash(self, temp_dir):
        """A numeric plugin name (e.g. ``"name": 123``) must not crash the
        docs renderers, which sort plugins by ``name.lower()`` (issue #322).
        ``lint`` tolerates this input, so ``docs`` must too.
        """
        plugin_dir = temp_dir / "numeric-name"
        plugin_dir.mkdir()
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(
            json.dumps({"name": 123, "description": "d", "version": "1.0"})
        )

        ctx = RepositoryContext(plugin_dir)
        docs = extract_docs(ctx)
        assert len(docs.plugins) == 1

        # Neither renderer should raise AttributeError on the int name.
        html_pages = render_html(docs)
        assert "index.html" in html_pages
        md_pages = render_markdown(docs)
        assert md_pages

    def test_render_numeric_marketplace_plugin_name_does_not_crash(self, temp_dir):
        """A numeric plugin name in marketplace.json must not crash the docs
        renderers either: the marketplace markdown path derives per-plugin
        page filenames from ``plugin.name`` string methods (issue #322).
        Non-string names are invalid (claude-marketplace-json-valid flags them), so
        name resolution degrades to the plugin's directory name.
        """
        claude_dir = temp_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": "test-marketplace",
                    "owner": {"name": "Owner"},
                    "plugins": [
                        {
                            "name": "alpha",
                            "source": "./plugins/alpha",
                            "description": "A well-formed plugin",
                        },
                        {
                            "name": 123,
                            "source": "./plugins/beta",
                            "description": "Numeric name",
                        },
                    ],
                }
            )
        )
        for dirname, name in (("alpha", "alpha"), ("beta", 123)):
            plugin_dir = temp_dir / "plugins" / dirname / ".claude-plugin"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                json.dumps({"name": name, "description": "d", "version": "1.0"})
            )

        ctx = RepositoryContext(temp_dir)
        docs = extract_docs(ctx)

        html_pages = render_html(docs)
        assert "index.html" in html_pages
        md_pages = render_markdown(docs)
        assert "README.md" in md_pages
        # The numeric-named plugin still gets a per-plugin page, keyed by
        # its directory name (the fallback for invalid non-string names).
        assert "beta.md" in md_pages

    def test_render_falsy_plugin_name_preserved(self):
        """A falsy-but-valid plugin name (``0``) must be preserved by the
        renderers' name coercion, not collapsed to ``""`` the way
        ``str(name or "")`` would (review feedback on issue #322 fixes).
        Constructed directly because the extractor's name-resolution chain
        substitutes a fallback before falsy names reach the renderers.
        """
        plugin = PluginDoc(name=0, path=Path("plugins/zero"), description="d")
        docs = DocsOutput(
            repo_type=RepositoryType.MARKETPLACE,
            title="t",
            marketplace=MarketplaceDoc(name="m", plugins=[plugin]),
            plugins=[plugin],
        )
        md_pages = render_markdown(docs)
        # Preserved as "0", not collapsed to "" (which would yield ".md").
        assert "0.md" in md_pages
        assert ".md" not in md_pages
        html_pages = render_html(docs)
        assert "index.html" in html_pages

    def test_custom_title(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx, title="My Custom Title")
        assert docs.title == "My Custom Title"

    def test_default_title_from_plugin_name(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        assert docs.title == "test-plugin"

    def test_default_title_from_marketplace_name(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        assert docs.title == "test-marketplace"

    def test_extract_marketplace_plugin_metadata(self, temp_dir):
        """Marketplace entry fields (category, tags, keywords, displayName, etc.) are extracted."""
        claude_dir = temp_dir / ".claude-plugin"
        claude_dir.mkdir()

        marketplace_json = {
            "name": "meta-marketplace",
            "owner": {"name": "Test"},
            "plugins": [
                {
                    "name": "rich-plugin",
                    "source": "./plugins/rich-plugin",
                    "description": "A richly annotated plugin",
                    "displayName": "Rich Plugin",
                    "category": "bundle",
                    "tags": ["testing", "ci"],
                    "keywords": ["lint", "format"],
                    "homepage": "https://example.com",
                    "repository": "https://github.com/example/rich-plugin",
                    "license": "MIT",
                    "author": {"name": "Jane Doe"},
                }
            ],
        }
        (claude_dir / "marketplace.json").write_text(json.dumps(marketplace_json))

        plugin_dir = temp_dir / "plugins" / "rich-plugin"
        plugin_dir.mkdir(parents=True)
        plugin_claude = plugin_dir / ".claude-plugin"
        plugin_claude.mkdir()
        (plugin_claude / "plugin.json").write_text(
            json.dumps({"name": "rich-plugin", "description": "A richly annotated plugin"})
        )
        commands_dir = plugin_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "noop.md").write_text(
            "---\ndescription: noop\n---\n\n## Name\nrich-plugin:noop\n"
        )

        ctx = RepositoryContext(temp_dir)
        docs = extract_docs(ctx)
        assert docs.marketplace is not None
        plugin = docs.marketplace.plugins[0]
        assert plugin.display_name == "Rich Plugin"
        assert plugin.category == "bundle"
        assert plugin.tags == ["testing", "ci"]
        assert plugin.keywords == ["lint", "format"]
        assert plugin.homepage == "https://example.com"
        assert plugin.repository == "https://github.com/example/rich-plugin"
        assert plugin.license == "MIT"

    def test_extract_plugin_missing_optional_fields(self, valid_plugin):
        """Plugins without the new optional fields get safe defaults."""
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        plugin = docs.plugins[0]
        assert plugin.display_name == ""
        assert plugin.category == ""
        assert plugin.tags == []
        assert plugin.keywords == []
        assert plugin.homepage == ""
        assert plugin.repository == ""
        assert plugin.license == ""


# ---------------------------------------------------------------------------
# Agent Plugins extractor tests
# ---------------------------------------------------------------------------


AGENT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
AGENT_PLUGIN_MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"


def write_agent_plugin(root, name, *, manifest_text=None, skill="demo"):
    """Write a portable Agent Plugins package at *root*."""
    root.mkdir(parents=True, exist_ok=True)
    if manifest_text is None:
        manifest_text = json.dumps(
            {
                "$schema": AGENT_PLUGIN_SCHEMA,
                "name": name,
                "version": "1.4.0",
                "description": "Review release evidence.",
                "author": {"name": "Acme Release Engineering"},
                "homepage": "https://example.com/plugins/release-tools",
                "repository": "https://example.com/source/release-tools",
                "license": "Apache-2.0",
                "keywords": ["release", "audit"],
            }
        )
    (root / "plugin.json").write_text(manifest_text)

    (root / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": AGENT_PLUGIN_MCP_SCHEMA,
                "mcpServers": {
                    "release-auditor": {
                        "type": "stdio",
                        "command": "uvx",
                        "args": ["release-auditor"],
                    }
                },
            }
        )
    )

    skill_dir = root / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: Audits release evidence before a ship decision.\n"
        f"---\n\n# {skill}\n\nCollect the evidence.\n"
    )

    commands_dir = root / "commands"
    commands_dir.mkdir()
    (commands_dir / "audit.md").write_text(
        "---\ndescription: Audit a release\n---\n\n"
        "## Name\naudit\n\n## Description\nAudits a release.\n"
    )
    (root / "README.md").write_text(f"# {name}\n\nPortable package.\n")
    return root


class TestAgentPluginExtractor:
    def test_extract_root_package(self, temp_dir):
        """A repo-root Agent Plugin becomes a PluginDoc with its own content."""
        write_agent_plugin(temp_dir, "acme.release-tools")

        ctx = RepositoryContext(temp_dir)
        docs = extract_docs(ctx)

        assert docs.repo_type == RepositoryType.AGENT_PLUGIN
        assert len(docs.plugins) == 1
        plugin = docs.plugins[0]
        assert plugin.name == "acme.release-tools"
        assert plugin.version == "1.4.0"
        assert plugin.description == "Review release evidence."
        assert plugin.author == {"name": "Acme Release Engineering"}
        assert plugin.homepage == "https://example.com/plugins/release-tools"
        assert plugin.repository == "https://example.com/source/release-tools"
        assert plugin.license == "Apache-2.0"
        assert plugin.keywords == ["release", "audit"]
        assert plugin.has_readme is True

        assert [s.name for s in plugin.skills] == ["demo"]
        assert [c.name for c in plugin.commands] == ["audit"]
        # The package's skills belong to it, not to the repository at large.
        assert docs.skills == []

    def test_root_package_mcp_servers(self, temp_dir):
        """The portable mcp.json is published like any other MCP config."""
        write_agent_plugin(temp_dir, "acme.release-tools")

        docs = extract_docs(RepositoryContext(temp_dir))
        servers = docs.plugins[0].mcp_servers
        assert [s.name for s in servers] == ["release-auditor"]
        assert servers[0].server_type == "stdio"
        assert servers[0].source_file == "mcp.json"
        assert servers[0].config["command"] == "uvx"

    def test_extract_plugins_collection(self, temp_dir):
        """Every plugins/* package is documented under its own package."""
        write_agent_plugin(temp_dir / "plugins" / "alpha", "acme.alpha", skill="alpha-skill")
        write_agent_plugin(temp_dir / "plugins" / "beta", "acme.beta", skill="beta-skill")

        docs = extract_docs(RepositoryContext(temp_dir))

        by_name = {p.name: p for p in docs.plugins}
        assert set(by_name) == {"acme.alpha", "acme.beta"}
        assert [s.name for s in by_name["acme.alpha"].skills] == ["alpha-skill"]
        assert [s.name for s in by_name["acme.beta"].skills] == ["beta-skill"]
        assert [s.name for s in by_name["acme.beta"].mcp_servers] == ["release-auditor"]
        assert docs.skills == []

    def test_malformed_manifest_falls_back_to_directory_name(self, temp_dir):
        """An unparseable manifest still publishes the package it names."""
        package = temp_dir / "plugins" / "release-tools"
        write_agent_plugin(
            package,
            "acme.release-tools",
            # Trailing comma: discovery recognizes the schema from the raw
            # text, but json.loads never yields metadata.
            manifest_text='{\n  "$schema": "%s",\n  "name": "acme.release-tools",\n}\n'
            % AGENT_PLUGIN_SCHEMA,
        )

        docs = extract_docs(RepositoryContext(temp_dir))

        assert len(docs.plugins) == 1
        plugin = docs.plugins[0]
        assert plugin.name == "release-tools"
        assert plugin.version == ""
        assert plugin.description == ""
        assert plugin.author is None
        assert plugin.keywords == []
        # The package still owns its content — a bad manifest must not
        # scatter the skills back into the repository's standalone list.
        assert [s.name for s in plugin.skills] == ["demo"]
        assert [s.name for s in plugin.mcp_servers] == ["release-auditor"]
        assert docs.skills == []

    def test_non_string_manifest_fields_do_not_crash(self, temp_dir):
        """Wrong-typed manifest values degrade to defaults, never to a crash."""
        write_agent_plugin(
            temp_dir,
            "acme.release-tools",
            manifest_text=json.dumps(
                {
                    "$schema": AGENT_PLUGIN_SCHEMA,
                    "name": 42,
                    "version": 18,
                    "description": False,
                    "author": "Acme Release Engineering",
                    "keywords": "release",
                    "homepage": "javascript:alert(1)",
                }
            ),
        )

        docs = extract_docs(RepositoryContext(temp_dir))
        plugin = docs.plugins[0]
        assert plugin.name == temp_dir.name
        assert plugin.version == "18"
        assert plugin.description == ""
        assert plugin.author == {"name": "Acme Release Engineering"}
        assert plugin.keywords == []
        assert plugin.homepage == ""
        assert render_markdown(docs)["README.md"]

    def test_dual_ecosystem_package_documented_once(self, temp_dir):
        """A Claude plugin that also ships a portable manifest is not doubled."""
        write_agent_plugin(temp_dir, "acme.release-tools")
        claude_dir = temp_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(
            json.dumps({"name": "release-tools", "version": "2.0.0"})
        )

        docs = extract_docs(RepositoryContext(temp_dir))

        assert len(docs.plugins) == 1
        assert docs.plugins[0].name == "release-tools"
        # The Claude doc still carries the portable components.
        assert [s.name for s in docs.plugins[0].skills] == ["demo"]
        assert [s.name for s in docs.plugins[0].mcp_servers] == ["release-auditor"]

    def test_root_package_renders(self, temp_dir):
        """Both renderers publish the package rather than an empty page."""
        write_agent_plugin(temp_dir, "acme.release-tools")
        docs = extract_docs(RepositoryContext(temp_dir))

        markdown = render_markdown(docs)["README.md"]
        assert "acme.release-tools" in markdown
        assert "demo" in markdown
        assert "release-auditor" in markdown

        html = render_html(docs)["index.html"]
        assert "acme.release-tools" in html
        assert "release-auditor" in html


# ---------------------------------------------------------------------------
# HTML renderer tests
# ---------------------------------------------------------------------------


class TestHtmlRenderer:
    def test_single_page_valid_html(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        pages = render_html(docs)
        assert "index.html" in pages
        assert len(pages) == 1

        page = pages["index.html"]
        assert page.startswith("<!DOCTYPE html>")
        assert "</html>" in page
        assert "<style>" in page

    def test_single_page_contains_content(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]

        assert "test-plugin" in page
        assert "test-command" in page
        assert "Runs a test workflow and reports the result" in page

    def test_marketplace_single_page(self, marketplace_repo):
        """Marketplace renders as a single page with embedded data."""
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        pages = render_html(docs)

        assert len(pages) == 1
        assert "index.html" in pages

        page = pages["index.html"]
        assert "plugin-one" in page
        assert "plugin-two" in page

    def test_marketplace_has_embedded_data(self, marketplace_repo):
        """Marketplace page includes plugin data as embedded JSON."""
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]

        assert "var DATA =" in page
        assert "IS_MARKETPLACE = true" in page

    def test_non_marketplace_flag(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]

        assert "IS_MARKETPLACE = false" in page

    def test_html_escapes_content(self, temp_dir):
        """XSS protection: user content is escaped."""
        plugin_dir = temp_dir / "xss-plugin"
        plugin_dir.mkdir()
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(
            json.dumps({"name": '<script>alert("xss")</script>', "description": "safe"})
        )

        ctx = RepositoryContext(plugin_dir)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        assert "<script>alert" not in page
        assert "&lt;script&gt;" in page

    def test_escattr_guards_missing_values(self, valid_plugin):
        """escAttr(undefined) must render '', not the literal 'undefined'.

        The card template calls escAttr(p.category) for every plugin, and
        String(undefined) is the truthy string "undefined" — so without the
        falsy guard an omitted category becomes data-category="undefined".
        The JS runs client-side, so assert on the shipped helper source.
        """
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        escattr = page.split("function escAttr(str) {", 1)[1].split("function", 1)[0]
        assert "if (!str) return '';" in escattr

    def test_dot_claude_sections(self, dot_claude_repo):
        ctx = RepositoryContext(dot_claude_repo)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]

        assert "greet" in page
        assert "review" in page
        assert "helper" in page
        assert "PostToolUse" in page
        assert "style" in page

    def test_navbar_stats(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        assert "navbar-stats" in page

    def test_marketplace_sorted_alphabetically(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        pos_one = page.index("plugin-one")
        pos_two = page.index("plugin-two")
        assert pos_one < pos_two

    def test_has_search(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        assert "search" in page
        assert "search-input" in page

    def test_search_covers_commands(self, valid_plugin):
        """Search data includes command information for cross-type searching."""
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        assert "doSearch" in page
        assert "commands" in page

    def test_inline_markdown_rendered(self, temp_dir):
        """Inline markdown (backticks, bold, links) is rendered in embedded data."""
        plugin_dir = temp_dir / "md-plugin"
        plugin_dir.mkdir()
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(
            json.dumps({"name": "md-plugin", "description": "safe"})
        )
        commands_dir = plugin_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "test.md").write_text(
            "---\ndescription: Uses `gh` CLI to **fetch** data\n---\n\n"
            "## Name\nmd-plugin:test\n\n"
            "## Description\n"
            "Check [GitHub](https://github.com) for `issues`.\n"
        )

        ctx = RepositoryContext(plugin_dir)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        # HTML tags are unicode-escaped in the embedded JSON for XSS safety
        assert "\\u003ccode\\u003egh\\u003c/code\\u003e" in page
        assert "\\u003cstrong\\u003efetch\\u003c/strong\\u003e" in page
        assert "https://github.com" in page
        # Raw markdown appears in the plain-text description field (for search),
        # but the description_html field has the rendered version
        assert "description_html" in page

    def test_inline_markdown_xss_safe(self, temp_dir):
        """Markdown rendering still escapes HTML to prevent XSS."""
        plugin_dir = temp_dir / "xss2"
        plugin_dir.mkdir()
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(json.dumps({"name": "xss2", "description": "safe"}))
        commands_dir = plugin_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "test.md").write_text(
            '---\ndescription: Try <script>alert("xss")</script> injection\n---\n\n'
            "## Name\nxss2:test\n"
        )

        ctx = RepositoryContext(plugin_dir)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        assert "<script>alert" not in page

    def test_detail_view_support(self, marketplace_repo):
        """Marketplace pages include plugin detail view."""
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        assert "showPluginDetail" in page
        assert "detail-back" in page

    def test_dark_theme(self, valid_plugin):
        """Page uses the dark theme."""
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        assert "--bg-dark: #0f0f0f" in page
        assert "--bg-card: #1a1a1a" in page

    def test_semantic_html(self, valid_plugin):
        """Page uses semantic HTML elements."""
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        assert "<nav " in page
        assert "<main " in page
        assert "<section " in page
        assert "<footer>" in page

    def test_html_contains_marketplace_metadata(self, temp_dir):
        """HTML output includes category, tags, displayName, homepage, repository, license."""
        claude_dir = temp_dir / ".claude-plugin"
        claude_dir.mkdir()
        marketplace_json = {
            "name": "rich-mp",
            "owner": {"name": "Test"},
            "plugins": [
                {
                    "name": "rp",
                    "source": "./plugins/rp",
                    "description": "Rich plugin",
                    "displayName": "Rich Plugin Display",
                    "category": "security",
                    "tags": ["audit", "scan"],
                    "keywords": ["vuln"],
                    "homepage": "https://example.com/rp",
                    "repository": "https://github.com/test/rp",
                    "license": "Apache-2.0",
                    "author": {"name": "Alice"},
                }
            ],
        }
        (claude_dir / "marketplace.json").write_text(json.dumps(marketplace_json))
        plugin_dir = temp_dir / "plugins" / "rp"
        plugin_dir.mkdir(parents=True)
        p_claude = plugin_dir / ".claude-plugin"
        p_claude.mkdir()
        (p_claude / "plugin.json").write_text(
            json.dumps({"name": "rp", "description": "Rich plugin"})
        )
        commands_dir = plugin_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "x.md").write_text("---\ndescription: x\n---\n\n## Name\nrp:x\n")

        ctx = RepositoryContext(temp_dir)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]

        assert "Rich Plugin Display" in page
        assert "security" in page
        assert "audit" in page
        assert "scan" in page
        assert "vuln" in page
        assert "https://example.com/rp" in page
        assert "https://github.com/test/rp" in page
        assert "Apache-2.0" in page

    def test_html_category_filter(self, temp_dir):
        """Marketplace with categories renders a category filter."""
        claude_dir = temp_dir / ".claude-plugin"
        claude_dir.mkdir()
        marketplace_json = {
            "name": "cat-mp",
            "owner": {"name": "Test"},
            "plugins": [
                {
                    "name": "p1",
                    "source": "./plugins/p1",
                    "category": "ci",
                },
                {
                    "name": "p2",
                    "source": "./plugins/p2",
                    "category": "security",
                },
            ],
        }
        (claude_dir / "marketplace.json").write_text(json.dumps(marketplace_json))
        for pname in ["p1", "p2"]:
            pd = temp_dir / "plugins" / pname
            pd.mkdir(parents=True)
            pc = pd / ".claude-plugin"
            pc.mkdir()
            (pc / "plugin.json").write_text(
                json.dumps({"name": pname, "description": f"Plugin {pname}"})
            )
            cd = pd / "commands"
            cd.mkdir()
            (cd / "x.md").write_text(f"---\ndescription: x\n---\n\n## Name\n{pname}:x\n")

        ctx = RepositoryContext(temp_dir)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]

        assert "filterByCategory" in page
        assert "category-filter" in page

    def test_theme_applies_colors(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        page = render_html(docs, theme="ocean-blue")["index.html"]

        colors = COLOR_THEMES["ocean-blue"]
        assert colors["primary"] in page
        assert colors["primary_dark"] in page
        assert colors["secondary"] in page
        assert "#6366f1" not in page

    def test_theme_none_uses_defaults(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]

        assert "#6366f1" in page

    def test_title_override_respected(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx, title="Custom Title")
        page = render_html(docs)["index.html"]

        assert "<title>Custom Title</title>" in page

    def test_title_override_marketplace(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx, title="My Marketplace")
        page = render_html(docs)["index.html"]

        assert "<title>My Marketplace</title>" in page


# ---------------------------------------------------------------------------
# Markdown renderer tests
# ---------------------------------------------------------------------------


class TestMarkdownRenderer:
    def test_single_page(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        pages = render_markdown(docs)
        assert "README.md" in pages
        assert len(pages) == 1

        md = pages["README.md"]
        assert md.startswith("# test-plugin")
        assert "## Commands" in md
        assert "test-command" in md
        assert "skillsaw" in md

    def test_marketplace_multi_file(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        pages = render_markdown(docs)

        assert "README.md" in pages
        assert "plugin-one.md" in pages
        assert "plugin-two.md" in pages
        assert len(pages) == 3

    def test_marketplace_cross_links(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        pages = render_markdown(docs)

        # Index links to plugin pages
        assert "[plugin-one](plugin-one.md)" in pages["README.md"]
        assert "[plugin-two](plugin-two.md)" in pages["README.md"]

        # Plugin pages link back
        assert "README.md" in pages["plugin-one.md"]

    def test_dot_claude_all_sections(self, dot_claude_repo):
        ctx = RepositoryContext(dot_claude_repo)
        docs = extract_docs(ctx)
        md = render_markdown(docs)["README.md"]

        assert "## Commands" in md
        assert "## Skills" in md
        assert "## Agents" in md
        assert "## Hooks" in md
        assert "## Rules" in md

    def test_marketplace_sorted_alphabetically(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        md = render_markdown(docs)["README.md"]
        pos_one = md.index("plugin-one")
        pos_two = md.index("plugin-two")
        assert pos_one < pos_two

    def test_url_parens_cannot_break_out_of_markdown_links(self):
        """A manifest URL containing ')' would close [Homepage](...) early
        and inject arbitrary Markdown — e.g. a remote tracking image."""
        from skillsaw.docs.extractor import _safe_url

        url = "https://safe.example/)![x](https://tracker.example/pixel"
        safe = _safe_url(url)
        assert ")" not in safe and "(" not in safe
        assert safe.startswith("https://safe.example/%29")
        # Ordinary URLs come through unchanged.
        assert _safe_url("https://example.com/docs") == "https://example.com/docs"

    def test_control_characters_are_stripped_from_page_names(self):
        """A NUL in a catalog name must not reach Path.write_text(), which
        raises and aborts docs generation for the whole catalog."""
        from skillsaw.docs.markdown_renderer import _plugin_filename
        from skillsaw.docs.models import PluginDoc

        doc = PluginDoc(name="bad\x00name\x1b", path=Path("plugins/bad"))
        filename = _plugin_filename(doc)
        assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in filename)
        assert filename.endswith(".md")

    def test_claude_only_sources_are_not_published_in_codex_docs(self, temp_dir):
        """A Codex catalog listing a directory with only a Claude manifest
        advertises a plugin Codex cannot install — the registration rule
        reports the unusable source, and docs must agree with it."""
        (temp_dir / ".agents" / "plugins").mkdir(parents=True)
        (temp_dir / ".agents" / "plugins" / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": "mixed-cat",
                    "plugins": [
                        {
                            "name": "claude-only",
                            "source": {"source": "local", "path": "./plugins/claude-only"},
                            "policy": {
                                "installation": "AVAILABLE",
                                "authentication": "ON_INSTALL",
                            },
                            "category": "Productivity",
                        },
                        {
                            "name": "codex-plug",
                            "source": {"source": "local", "path": "./plugins/codex-plug"},
                            "policy": {
                                "installation": "AVAILABLE",
                                "authentication": "ON_INSTALL",
                            },
                            "category": "Productivity",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        claude_dir = temp_dir / "plugins" / "claude-only" / ".claude-plugin"
        claude_dir.mkdir(parents=True)
        (claude_dir / "plugin.json").write_text(
            json.dumps({"name": "claude-only", "version": "1.0.0", "description": "Claude."})
        )
        codex_dir = temp_dir / "plugins" / "codex-plug" / ".codex-plugin"
        codex_dir.mkdir(parents=True)
        (codex_dir / "plugin.json").write_text(
            json.dumps({"name": "codex-plug", "version": "1.0.0", "description": "Codex."})
        )

        ctx = RepositoryContext(temp_dir)
        docs = extract_docs(ctx)
        assert docs.marketplace is not None
        listed = {str(p.name) for p in docs.marketplace.plugins}
        assert "codex-plug" in listed
        assert "claude-only" not in listed

    def test_remote_metadata_newlines_cannot_inject_markdown(self):
        """A remote catalog entry controls version/license/category — a
        newline in one would end the meta line and inject block Markdown."""
        from skillsaw.docs.markdown_renderer import _append_plugin_meta
        from skillsaw.docs.models import PluginDoc

        doc = PluginDoc(
            name="remote-plug",
            path=Path("plugins/remote-plug"),
            version="1.0\n\n![track](https://tracker.example/pixel)",
            license="MIT",
        )
        lines: list = []
        _append_plugin_meta(lines, doc)
        assert not any(line.startswith("![") for line in lines)
        meta_line = next(line for line in lines if "**Version:**" in line)
        # Folded onto the meta line AND link syntax escaped — the image
        # markup arrives inert.
        assert "![track](" not in meta_line
        assert r"!\[track\]" in meta_line
        assert "**License:** MIT" in meta_line

    def test_mcp_table_escapes_pipes_and_newlines(self):
        """A valid command may contain '|' or a newline; neither may corrupt
        the table — the pipe adds a column, the newline ends the row."""
        from skillsaw.docs.markdown_renderer import _append_mcp_table
        from skillsaw.docs.models import McpServerDoc

        lines: list = []
        _append_mcp_table(
            lines,
            [
                McpServerDoc(
                    name="log|ger",
                    server_type="stdio",
                    config={"command": "node server.js | tee log\nrm -rf /"},
                    source_file=".mcp.json",
                )
            ],
        )
        rows = [line for line in lines if line.startswith("|")]
        # Header, separator, and exactly one data row — the newline must not
        # have split the entry into a second row.
        assert len(rows) == 3
        data_row = rows[2]
        assert data_row.count(" | ") == 3
        assert r"log\|ger" in data_row
        assert "rm -rf /" in data_row  # folded onto the same line, not lost

    def test_skill_metadata_in_markdown(self, dot_claude_repo):
        ctx = RepositoryContext(dot_claude_repo)
        docs = extract_docs(ctx)
        md = render_markdown(docs)["README.md"]

        assert "MIT" in md
        assert "code-review:pr" in md

    def test_markdown_contains_marketplace_metadata(self, temp_dir):
        """Markdown output includes category, tags, displayName, homepage, repository, license."""
        claude_dir = temp_dir / ".claude-plugin"
        claude_dir.mkdir()
        marketplace_json = {
            "name": "rich-mp",
            "owner": {"name": "Test"},
            "plugins": [
                {
                    "name": "rp",
                    "source": "./plugins/rp",
                    "description": "Rich plugin",
                    "displayName": "Rich Plugin Display",
                    "category": "security",
                    "tags": ["audit", "scan"],
                    "keywords": ["vuln"],
                    "homepage": "https://example.com/rp",
                    "repository": "https://github.com/test/rp",
                    "license": "Apache-2.0",
                    "author": {"name": "Alice"},
                }
            ],
        }
        (claude_dir / "marketplace.json").write_text(json.dumps(marketplace_json))
        plugin_dir = temp_dir / "plugins" / "rp"
        plugin_dir.mkdir(parents=True)
        p_claude = plugin_dir / ".claude-plugin"
        p_claude.mkdir()
        (p_claude / "plugin.json").write_text(
            json.dumps({"name": "rp", "description": "Rich plugin"})
        )
        commands_dir = plugin_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "x.md").write_text("---\ndescription: x\n---\n\n## Name\nrp:x\n")

        ctx = RepositoryContext(temp_dir)
        docs = extract_docs(ctx)
        pages = render_markdown(docs)

        # Index uses displayName
        assert "[Rich Plugin Display](rp.md)" in pages["README.md"]

        # Plugin page heading uses displayName
        plugin_md = pages["rp.md"]
        assert "# Rich Plugin Display" in plugin_md

        # Metadata fields rendered
        assert "**License:** Apache-2.0" in plugin_md
        assert "**Category:** security" in plugin_md
        assert "[Homepage](https://example.com/rp)" in plugin_md
        assert "[Repository](https://github.com/test/rp)" in plugin_md
        assert "`audit`" in plugin_md
        assert "`scan`" in plugin_md
        assert "`vuln`" in plugin_md


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestDocsCLI:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "skillsaw", "docs", *args],
            capture_output=True,
            text=True,
        )

    def test_docs_help(self):
        result = self._run("--help")
        assert result.returncode == 0
        assert "Generate documentation" in result.stdout

    def test_docs_generates_html(self, valid_plugin, temp_dir):
        out_dir = temp_dir / "out"
        result = self._run(str(valid_plugin), "--output", str(out_dir))
        assert result.returncode == 0
        assert (out_dir / "index.html").exists()
        content = (out_dir / "index.html").read_text()
        assert "<!DOCTYPE html>" in content

    def test_docs_generates_markdown(self, valid_plugin, temp_dir):
        out_dir = temp_dir / "out"
        result = self._run(str(valid_plugin), "--format", "markdown", "--output", str(out_dir))
        assert result.returncode == 0
        assert (out_dir / "README.md").exists()

    def test_docs_marketplace_single_page(self, marketplace_repo, temp_dir):
        """Marketplace generates a single index.html."""
        out_dir = temp_dir / "out"
        result = self._run(str(marketplace_repo), "--output", str(out_dir))
        assert result.returncode == 0
        assert (out_dir / "index.html").exists()
        content = (out_dir / "index.html").read_text()
        assert "plugin-one" in content
        assert "plugin-two" in content

    def test_docs_custom_title(self, valid_plugin, temp_dir):
        out_dir = temp_dir / "out"
        result = self._run(str(valid_plugin), "--output", str(out_dir), "--title", "Custom Title")
        assert result.returncode == 0
        content = (out_dir / "index.html").read_text()
        assert "Custom Title" in content

    def test_lint_still_works(self, valid_plugin):
        """Backward compat: bare skillsaw still runs the linter."""
        result = subprocess.run(
            [sys.executable, "-m", "skillsaw", str(valid_plugin)],
            capture_output=True,
            text=True,
        )
        assert "Linting:" in result.stdout

    def test_invalid_path(self, temp_dir):
        result = self._run(str(temp_dir / "nonexistent"))
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()

    def test_docs_apm_repo_finds_skills(self, temp_dir):
        """Repos with .apm/ should generate docs for .apm/skills/ (source, not compiled output)."""
        apm_dir = temp_dir / ".apm"
        apm_dir.mkdir()
        skills_dir = apm_dir / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill\n---\n\nDo the thing.\n"
        )
        out_dir = temp_dir / "out"
        result = self._run(str(temp_dir), "--format", "markdown", "--output", str(out_dir))
        assert result.returncode == 0
        readme = (out_dir / "README.md").read_text()
        assert "my-skill" in readme
        assert "A test skill" in readme
