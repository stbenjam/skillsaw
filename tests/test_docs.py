"""Tests for the docs subcommand: extractor, HTML renderer, markdown renderer, and CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.docs.extractor import extract_docs
from skillsaw.docs.html_renderer import render_html
from skillsaw.docs.markdown_renderer import render_markdown

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
        assert plugin.commands[0].description == "A test command"
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
        assert "A test command" in page

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

    def test_modal_support(self, marketplace_repo):
        """Marketplace pages include modal infrastructure."""
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        page = render_html(docs)["index.html"]
        assert "modal" in page
        assert "showPluginModal" in page

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


# ---------------------------------------------------------------------------
# Markdown renderer tests
# ---------------------------------------------------------------------------


class TestMarkdownRenderer:
    def test_single_page(self, valid_plugin):
        ctx = RepositoryContext(valid_plugin)
        docs = extract_docs(ctx)
        pages = render_markdown(docs)
        assert "index.md" in pages
        assert len(pages) == 1

        md = pages["index.md"]
        assert md.startswith("# test-plugin")
        assert "## Commands" in md
        assert "test-command" in md
        assert "skillsaw" in md

    def test_marketplace_multi_file(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        pages = render_markdown(docs)

        assert "index.md" in pages
        assert "plugin-one.md" in pages
        assert "plugin-two.md" in pages
        assert len(pages) == 3

    def test_marketplace_cross_links(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        pages = render_markdown(docs)

        # Index links to plugin pages
        assert "[plugin-one](plugin-one.md)" in pages["index.md"]
        assert "[plugin-two](plugin-two.md)" in pages["index.md"]

        # Plugin pages link back
        assert "index.md" in pages["plugin-one.md"]

    def test_dot_claude_all_sections(self, dot_claude_repo):
        ctx = RepositoryContext(dot_claude_repo)
        docs = extract_docs(ctx)
        md = render_markdown(docs)["index.md"]

        assert "## Commands" in md
        assert "## Skills" in md
        assert "## Agents" in md
        assert "## Hooks" in md
        assert "## Rules" in md

    def test_marketplace_sorted_alphabetically(self, marketplace_repo):
        ctx = RepositoryContext(marketplace_repo)
        docs = extract_docs(ctx)
        md = render_markdown(docs)["index.md"]
        pos_one = md.index("plugin-one")
        pos_two = md.index("plugin-two")
        assert pos_one < pos_two

    def test_skill_metadata_in_markdown(self, dot_claude_repo):
        ctx = RepositoryContext(dot_claude_repo)
        docs = extract_docs(ctx)
        md = render_markdown(docs)["index.md"]

        assert "MIT" in md
        assert "code-review:pr" in md


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
        result = self._run(str(valid_plugin), "--output-dir", str(out_dir))
        assert result.returncode == 0
        assert (out_dir / "index.html").exists()
        content = (out_dir / "index.html").read_text()
        assert "<!DOCTYPE html>" in content

    def test_docs_generates_markdown(self, valid_plugin, temp_dir):
        out_dir = temp_dir / "out"
        result = self._run(str(valid_plugin), "--format", "markdown", "--output-dir", str(out_dir))
        assert result.returncode == 0
        assert (out_dir / "index.md").exists()

    def test_docs_marketplace_single_page(self, marketplace_repo, temp_dir):
        """Marketplace generates a single index.html."""
        out_dir = temp_dir / "out"
        result = self._run(str(marketplace_repo), "--output-dir", str(out_dir))
        assert result.returncode == 0
        assert (out_dir / "index.html").exists()
        content = (out_dir / "index.html").read_text()
        assert "plugin-one" in content
        assert "plugin-two" in content

    def test_docs_custom_title(self, valid_plugin, temp_dir):
        out_dir = temp_dir / "out"
        result = self._run(
            str(valid_plugin), "--output-dir", str(out_dir), "--title", "Custom Title"
        )
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
