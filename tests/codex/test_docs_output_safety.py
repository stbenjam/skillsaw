"""Generated-docs output safety: filenames, escaping, and link schemes."""

import json
from pathlib import Path

import pytest

from skillsaw.docs.extractor import extract_docs
from skillsaw.docs.models import PluginDoc
from skillsaw.docs.html_renderer import render_html
from skillsaw.docs.markdown_renderer import _plugin_filename, render_markdown
from skillsaw.context import RepositoryContext

from ._helpers import _write_plugin, _codex_plugin_repo, _codex_marketplace_repo


class TestDocsAuthorshipAndFilenames:
    def test_installed_plugins_are_not_published_as_catalog_members(self, tmp_path):
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": []})
        installed = repo / ".codex" / "plugins" / "vendor"
        installed.mkdir(parents=True)
        _write_plugin(installed, {"name": "vendor", "version": "1.0.0", "description": "Theirs."})

        docs = extract_docs(RepositoryContext(repo))
        assert [p.name for p in docs.plugins] == []

    @pytest.mark.parametrize(
        "name", ["..\\\\..\\\\evil", "C:\\\\temp\\\\x", "../../evil", "a/b", ".."]
    )
    def test_a_hostile_plugin_name_cannot_escape_the_output_directory(self, name):
        """A kebab-case violation is only a warning, so `docs` cannot assume
        `lint` rejected the name first."""
        doc = PluginDoc(name=name, path=Path("/x"), description="", version="")
        filename = _plugin_filename(doc)

        assert "/" not in filename
        assert "\\" not in filename
        assert ":" not in filename
        assert ".." not in filename


class TestFilenameCaseFolding:
    def test_names_differing_only_by_case_get_distinct_files(self, tmp_path):
        """`Foo.md` and `foo.md` are one file on default macOS and Windows."""
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
                    for i, n in enumerate(["Foo", "foo"])
                ],
            },
        )
        pages = render_markdown(extract_docs(RepositoryContext(repo)))
        keys = [k.casefold() for k in pages if k != "README.md"]
        assert len(set(keys)) == 2, f"case-insensitive collision: {sorted(pages)}"


class TestIndexPageFilenameIsReserved:
    def test_a_plugin_named_readme_does_not_overwrite_the_index(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "readme",
                        "source": {"source": "local", "path": "./plugins/readme"},
                    },
                    {
                        "name": "other",
                        "source": {"source": "local", "path": "./plugins/other"},
                    },
                ],
            },
        )
        _write_plugin(repo / "plugins" / "readme", {"name": "readme", "version": "1.0.0"})
        _write_plugin(repo / "plugins" / "other", {"name": "other", "version": "1.0.0"})

        pages = render_markdown(extract_docs(RepositoryContext(repo)))
        assert "readme-2.md" in pages
        assert "## Plugins" in pages["README.md"]


class TestReservedFilenames:
    @pytest.mark.parametrize("name", ["con", "NUL", "com1", "LPT9", "aux"])
    def test_a_windows_device_name_is_not_used_verbatim(self, tmp_path, name):
        """`con.md` cannot be created on Windows — the whole run fails."""
        doc = PluginDoc(name=name, path=Path("/x"), description="", version="")
        assert _plugin_filename(doc).casefold() != f"{name.casefold()}.md"

    def test_an_ordinary_name_is_untouched(self, tmp_path):
        doc = PluginDoc(name="console", path=Path("/x"), description="", version="")
        assert _plugin_filename(doc) == "console.md"


class TestGeneratedFilenamesAreWritable:
    def test_a_name_longer_than_the_component_limit_is_bounded(self, tmp_path):
        doc = PluginDoc(name="a" * 400, path=Path("/x"), description="", version="")
        name = _plugin_filename(doc)
        assert len(name.encode("utf-8")) <= 255

    def test_two_long_names_still_get_distinct_files(self, tmp_path):
        a = _plugin_filename(PluginDoc(name="a" * 400, path=Path("/x")))
        b = _plugin_filename(PluginDoc(name="a" * 399 + "b", path=Path("/x")))
        assert a != b


class TestGeneratedHtmlEscaping:
    @pytest.mark.parametrize("category", ["Developer's Tools", "x');alert(document.domain);//"])
    def test_a_quote_in_a_category_cannot_break_out_of_the_handler(self, tmp_path, category):
        """innerHTML decodes entities before the handler compiles, so
        entity-encoding the quote does not contain it."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "one",
                        "source": {"source": "local", "path": "./plugins/one"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": category,
                    }
                ],
            },
        )
        _write_plugin(
            repo / "plugins" / "one",
            {"name": "one", "version": "1.0.0", "interface": {"category": category}},
        )
        html = "\n".join(render_html(extract_docs(RepositoryContext(repo))).values())

        assert "&#39;" not in html, "an entity-encoded quote decodes back to a live quote"


class TestGeneratedLinkSchemes:
    @pytest.mark.parametrize("field", ["homepage", "repository"])
    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(document.domain)",
            "JavaScript:alert(1)",
            "data:text/html,<x>",
        ],
    )
    def test_an_unsafe_scheme_is_dropped(self, tmp_path, field, url):
        """HTML-escaping an href stops attribute breakout, not the scheme."""
        repo = _codex_plugin_repo(
            tmp_path,
            {"name": "linky", "version": "1.0.0", "description": "x", field: url},
        )
        doc = extract_docs(RepositoryContext(repo)).plugins[0]
        assert getattr(doc, field) == ""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com",
            "http://example.com/x",
            "mailto:a@example.com",
            "./local",
        ],
    )
    def test_a_safe_url_is_kept(self, tmp_path, url):
        repo = _codex_plugin_repo(
            tmp_path,
            {"name": "linky", "version": "1.0.0", "description": "x", "homepage": url},
        )
        assert extract_docs(RepositoryContext(repo)).plugins[0].homepage == url


class TestGeneratedHtmlAttributeEscaping:
    """``esc()`` serialises a text node — the double quote it leaves alone
    closes an attribute value, and a second handler can follow it.

    The card markup is assembled by the page's own JavaScript, which no
    Python test can execute, so the assertions are on the two halves that
    together make the breakout impossible: every attribute value goes
    through an attribute-context escaper, and that escaper escapes the
    double quote.
    """

    def _rendered(self, tmp_path):
        category = 'x" onmouseover="alert(document.domain)'
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "one",
                        "source": {"source": "local", "path": "./plugins/one"},
                        "category": category,
                    }
                ],
            },
        )
        _write_plugin(
            repo / "plugins" / "one",
            {"name": "one", "version": "1.0.0", "interface": {"category": category}},
        )
        return "\n".join(render_html(extract_docs(RepositoryContext(repo))).values())

    def test_attribute_values_use_an_attribute_context_escaper(self, tmp_path):
        html = self._rendered(tmp_path)
        for line in html.splitlines():
            if "data-category=" in line and "+" in line:
                assert "escAttr(" in line
                break
        else:
            pytest.fail("no data-category assembly found in the generated page")

    def test_the_attribute_escaper_escapes_the_double_quote(self, tmp_path):
        html = self._rendered(tmp_path)
        body = html.split("function escAttr", 1)[1].split("function", 1)[0]
        assert "&quot;" in body


class TestUrlValuesCannotBreakOutOfAnAttribute:
    """Scheme validation stops ``javascript:``. It says nothing about a
    quote inside an otherwise-allowed ``https:`` value."""

    @pytest.mark.parametrize("field", ["homepage", "repository"])
    def test_a_quote_in_a_url_is_rejected(self, tmp_path, field):
        hostile = 'https://example.invalid/" onmouseover="alert(document.domain)'
        repo = _codex_plugin_repo(
            tmp_path,
            {"name": "linky", "version": "1.0.0", "description": "x", field: hostile},
        )
        assert getattr(extract_docs(RepositoryContext(repo)).plugins[0], field) == ""

    def test_the_href_is_written_with_the_attribute_escaper(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "linky",
                "version": "1.0.0",
                "description": "x",
                "homepage": "https://example.com",
            },
        )
        html = "\n".join(render_html(extract_docs(RepositoryContext(repo))).values())
        assert "'<a href=\"'+escAttr(p.homepage)+'\">" in html

    def test_data_search_is_written_with_the_attribute_escaper(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path, {"name": "searchy", "version": "1.0.0", "description": "x"}
        )
        html = "\n".join(render_html(extract_docs(RepositoryContext(repo))).values())
        assert "data-search=\"'+escAttr(" in html
        assert "data-search=\"'+esc(" not in html


class TestGeneratedMarkdownLinkSchemes:
    """``html.escape`` stops a link target breaking out of the attribute.
    It says nothing about what the target *is*, and the result is inserted
    through ``innerHTML``."""

    @pytest.mark.parametrize(
        "target", ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<x>"]
    )
    def test_an_active_scheme_loses_its_anchor(self, tmp_path, target):
        from skillsaw.docs.html_renderer import _md

        out = _md(f"See [click]({target}) for details.")
        assert "<a" not in out
        assert "click" in out, "the author's text must survive"

    @pytest.mark.parametrize(
        "target",
        [
            "https://example.com",
            "http://x.test/y",
            "mailto:a@b.test",
            "./rel.md",
            "#frag",
        ],
    )
    def test_a_safe_target_still_links(self, tmp_path, target):
        from skillsaw.docs.html_renderer import _md

        assert f'href="{target}"' in _md(f"[t]({target})")

    def test_a_skill_description_cannot_smuggle_one_through(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path, {"name": "holder", "version": "1.0.0", "description": "x"}
        )
        skill = repo / "skills" / "worker"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: worker\n"
            "description: See [click](javascript:alert(1)) before running this\n"
            "---\n\n# Worker\n",
            encoding="utf-8",
        )
        html = "\n".join(render_html(extract_docs(RepositoryContext(repo))).values())
        assert 'href="javascript:' not in html


class TestSafeDisplay:
    def test_redaction_work_is_bounded_on_adversarial_values(self):
        """Adversarial values must cost near-constant work: the display
        cap is applied before the scan, so input size buys nothing.

        A scaling ratio, not a wall-clock bound — absolute timings are
        instrumentation-dependent: coverage tracing on Python <=3.11
        has no sys.monitoring backend and multiplies per-line cost.
        """
        import time

        from skillsaw.diagnostics import safe_display

        def cost(n: int) -> float:
            best = float("inf")
            for _ in range(3):
                for pattern in ("a", "a@", "@", "u:p@h.c/"):
                    s = (pattern * (n // len(pattern) + 1))[:n]
                    start = time.perf_counter()
                    out = safe_display(s)
                    best_candidate = time.perf_counter() - start
                    assert len(out) <= 501  # bounded output
                    best = min(best, best_candidate)
            return best

        t1, t4 = cost(60_000), cost(240_000)
        # Truncate-first keeps this near-constant (ratio ~1); a
        # quadratic scan would land near 16. 8 leaves headroom for noise.
        assert t4 < 8 * max(t1, 1e-4), (t1, t4)

    def test_truncation_does_not_leak_a_severed_credential(self):
        """A credential whose ``@`` falls beyond the display cap must not
        surface its head — the cut edge is treated like an ``@``."""
        from skillsaw.diagnostics import safe_display

        value = "x" * 490 + "user:" + "S" * 600 + "@host.example/path"
        out = safe_display(value)
        assert "SSSS" not in out
        assert "[redacted]" in out

    def test_a_long_delimiterless_credential_is_fully_redacted(self):
        """A >512-char userinfo must not have its head emitted when the
        backward search window is clipped."""
        from skillsaw.diagnostics import _redact_userinfo

        out = _redact_userinfo("u:" + "T" * 600 + "@h.example")
        assert "TTTT" not in out
        assert out == "[redacted]@h.example"


class TestRendererHardening:
    def test_unsafe_urls_are_neutralized_on_both_extraction_paths(self, tmp_path):
        """javascript: and paren-bearing URLs from either a Claude or a
        Codex manifest must not reach generated Markdown or HTML."""
        from skillsaw.docs.html_renderer import render_html

        repo = tmp_path / "mixed"
        claude = repo / "plugins" / "claude-plug" / ".claude-plugin"
        claude.mkdir(parents=True)
        (claude / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "claude-plug",
                    "version": "1.0.0",
                    "description": "Claude plugin.",
                    "homepage": "javascript:alert(1)",
                    "repository": "https://safe.example/)![x](https://evil/p",
                }
            ),
            encoding="utf-8",
        )
        (repo / "plugins" / "claude-plug" / "commands").mkdir()
        codex = repo / "plugins" / "codex-plug"
        _write_plugin(
            codex,
            {
                "name": "codex-plug",
                "version": "1.0.0",
                "description": "Codex plugin.",
                "homepage": "javascript:alert(2)",
            },
        )
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": "cat",
                    "plugins": [
                        {
                            "name": "codex-plug",
                            "source": {"source": "local", "path": "./plugins/codex-plug"},
                            "policy": {
                                "installation": "AVAILABLE",
                                "authentication": "ON_INSTALL",
                            },
                            "category": "Productivity",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        docs = extract_docs(RepositoryContext(repo))
        md_pages = render_markdown(docs)
        html_pages = render_html(docs)
        for content in (*md_pages.values(), *html_pages.values()):
            assert "javascript:alert" not in content
            assert "https://evil/p" not in content

    def test_entity_encoded_schemes_are_neutralized_in_both_renderers(self, tmp_path):
        """``javascript&#58;alert&#40;1&#41;`` carries no literal colon or
        paren, so it must be caught by entity decoding, not the character
        filter — in Markdown and HTML output alike."""
        from skillsaw.docs.html_renderer import render_html

        repo = tmp_path / "entities"
        for name, homepage in (
            ("colon-plug", "javascript&#58;alert&#40;1&#41;"),
            ("letter-plug", "&#106;avascript:alert(1)"),
        ):
            claude = repo / "plugins" / name / ".claude-plugin"
            claude.mkdir(parents=True)
            (claude / "plugin.json").write_text(
                json.dumps(
                    {
                        "name": name,
                        "version": "1.0.0",
                        "description": "A plugin.",
                        "homepage": homepage,
                    }
                ),
                encoding="utf-8",
            )
            (repo / "plugins" / name / "commands").mkdir()

        docs = extract_docs(RepositoryContext(repo))
        for content in (*render_markdown(docs).values(), *render_html(docs).values()):
            assert "javascript&#58;" not in content
            assert "&#106;avascript" not in content
            assert "javascript:alert" not in content

    def test_emitted_page_script_survives_backslash_escaping(self, tmp_path):
        """The JS template is a non-raw Python string — backslash halving
        once shipped an unparseable script and a blank page. Pin the
        emitted (post-halving) escJsAttr line, and parse every script
        block with node when it is available."""
        import shutil
        import subprocess

        from skillsaw.docs.html_renderer import _get_js

        assert ".replace(/\\\\/g, '\\\\\\\\').replace(/'/g, \"\\\\'\")" in _get_js()

        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        repo = tmp_path / "page"
        _write_plugin(repo, {"name": "page", "version": "1.0.0", "description": "A plugin."})
        docs = extract_docs(RepositoryContext(repo))
        from skillsaw.docs.html_renderer import render_html

        for content in render_html(docs).values():
            # Plain splitting, not a tag regex: the input is our own
            # renderer's output, where the tag is always lowercase — and
            # this is block extraction for a parser check, not sanitizing.
            blocks = [chunk.split("</script>")[0] for chunk in content.split("<script>")[1:]]
            assert blocks, "no script blocks found in rendered page"
            for i, script in enumerate(blocks):
                js = tmp_path / f"block{i}.js"
                js.write_text(script, encoding="utf-8")
                proc = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
                assert proc.returncode == 0, proc.stderr


class TestSafeUrlEntityDecoding:
    def test_safe_url_decodes_entities_before_scheme_validation(self):
        """CommonMark decodes character references in link destinations, so
        entity-encoded schemes must be rejected, single- or double-encoded."""
        from skillsaw.docs.extractor import _safe_url

        assert _safe_url("javascript&colon;alert(1)") == ""
        assert _safe_url("javascript&amp;colon;alert(1)") == ""
        assert _safe_url("javascript&#58;alert(1)") == ""
        # Legitimate URLs survive, decoded to their rendered form.
        assert _safe_url("https://ok.example/?a=1&amp;b=2") == "https://ok.example/?a=1&b=2"
        assert _safe_url("https://ok.example/path") == "https://ok.example/path"


class TestCodeSpanBreakout:
    def test_backticks_in_metadata_cannot_escape_code_spans(self, tmp_path):
        """Tags and MCP values render inside code spans, where a literal
        backtick terminates the span and injects raw Markdown."""
        repo = tmp_path / "claude-repo"
        plugin = repo / "plugins" / "cl"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "cl",
                    "version": "1.0.0",
                    "description": "A plugin.",
                    "keywords": ["safe", "x` [evil](https://evil.example) `y"],
                }
            ),
            encoding="utf-8",
        )
        (plugin / "commands").mkdir()

        docs = extract_docs(RepositoryContext(repo))
        for content in render_markdown(docs).values():
            assert "[evil](https://evil.example)" not in content


class TestMarkdownRendererHostileMetadata:
    def test_hostile_metadata_scalars_are_inert_in_markdown(self, tmp_path):
        """The Markdown renderer is a published sink too: metadata
        scalars must not carry raw HTML or active-scheme links into a
        generated page (T15). Description fields are author prose by
        design and excluded — see the threat model."""
        repo = tmp_path / "hostile"
        plugin = repo / "plugins" / "evil"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(
                {
                    "name": "evil",
                    "version": "<script>alert(1)</script>",
                    "description": "A plugin.",
                    "author": {"name": "<img src=x onerror=alert(1)>"},
                    "license": "<script>x</script>",
                    "category": "<b>cat</b>",
                    "keywords": ["<script>tag</script>"],
                    "homepage": "javascript:alert(1)",
                }
            ),
            encoding="utf-8",
        )
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text(
            "---\ndescription: Run it.\n---\nBody.\n", encoding="utf-8"
        )

        docs = extract_docs(RepositoryContext(repo))
        for content in render_markdown(docs).values():
            # No raw tag can form: angle brackets are entity-encoded, so
            # an ``onerror`` payload survives only as inert text.
            assert "<script" not in content
            assert "<img" not in content
            assert "<b>" not in content
            assert "javascript:alert" not in content

    def test_hostile_hook_metadata_is_inert_in_markdown(self, tmp_path):
        """Hook event names and matchers are the same class of value as the
        rest of the metadata scalars: an event name is an arbitrary JSON
        object key, a matcher an arbitrary string. Rendered raw, a newline
        in the key opened block Markdown mid-heading and a backtick in the
        matcher closed the code span around it."""
        event = (
            "SessionStart\n\n## Injected Heading\n\n"
            "[click me](javascript:alert(1))\n\n<img src=x onerror=alert(2)>"
        )
        matcher = "`</code> [x](javascript:alert(3))"
        repo = _codex_marketplace_repo(
            tmp_path, {"name": "cat", "plugins": [{"name": "p1", "source": "./plugins/p1"}]}
        )
        plugin = _write_plugin(
            repo / "plugins" / "p1", {"name": "p1", "version": "1.0.0", "description": "A plugin."}
        )
        (plugin / "hooks").mkdir()
        (plugin / "hooks" / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        event: [
                            {
                                "matcher": matcher,
                                "hooks": [{"type": "command", "command": "echo hi"}],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        rendered = render_markdown(extract_docs(RepositoryContext(repo)))
        joined = "\n".join(rendered.values())
        # Anti-vacuity: the hook section must have been rendered at all.
        assert "**Matcher:**" in joined
        for content in rendered.values():
            assert "<img" not in content
            assert "[click me](javascript:" not in content
            assert "[x](javascript:" not in content
            # One heading per event, never a second one the key wrote.
            assert "\n## Injected Heading" not in content

    def test_hostile_rule_globs_are_inert_in_markdown(self, tmp_path):
        """`rules/*.md` globs render inside code spans, so a backtick in a
        glob closes the span and the rest of the value becomes Markdown."""
        repo = _codex_marketplace_repo(
            tmp_path, {"name": "cat", "plugins": [{"name": "p1", "source": "./plugins/p1"}]}
        )
        plugin = _write_plugin(
            repo / "plugins" / "p1", {"name": "p1", "version": "1.0.0", "description": "A plugin."}
        )
        (plugin / "rules").mkdir()
        (plugin / "rules" / "style.md").write_text(
            "---\ndescription: Style rules.\n"
            'paths: ["src/**", "x` [evil](javascript:alert(1)) `y"]\n'
            "---\nUse two spaces.\n",
            encoding="utf-8",
        )

        rendered = render_markdown(extract_docs(RepositoryContext(repo)))
        joined = "\n".join(rendered.values())
        assert "**Paths:**" in joined
        assert "[evil](javascript:" not in joined
