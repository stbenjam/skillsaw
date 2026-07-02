"""Tests for the MarkdownDoc AST facade (markdown_doc.py).

Covers the line-number fidelity matrix from the migration design: every
construct's reported line/column must match its actual file position, since
fixes splice at these exact spans.
"""

import re
from pathlib import Path

import pytest

from skillsaw.markdown_doc import MarkdownDoc, splice
from skillsaw.markdown_doc import _ContentMap


def _doc(body: str, **kwargs) -> MarkdownDoc:
    return MarkdownDoc(body, **kwargs)


def _link_by_href(doc: MarkdownDoc, href: str):
    matches = [l for l in doc.links() if l.href == href]
    assert matches, f"no link with href {href!r}"
    return matches[0]


def _assert_dest_span_exact(body: str, link) -> None:
    """The destination span must slice out exactly the href text."""
    assert link.has_dest_span
    line_text = body.split("\n")[link.dest_body_line - 1]
    assert line_text[link.dest_col_start : link.dest_col_end] == link.href


class TestFidelityMatrix:
    """Each case asserts the construct's reported line equals its actual file line."""

    def test_link_on_wrapped_paragraph_continuation_line(self):
        body = "first line of a wrapped paragraph\nsecond line with [x](docs/a.md) link\nthird line continues here\n"
        link = _link_by_href(_doc(body), "docs/a.md")
        assert link.body_line == 2
        assert link.dest_body_line == 2
        _assert_dest_span_exact(body, link)

    def test_link_inside_blockquote_continuation_line(self):
        body = "> quoted first line\n> quoted second with [x](docs/b.md) link\n"
        link = _link_by_href(_doc(body), "docs/b.md")
        assert link.body_line == 2
        _assert_dest_span_exact(body, link)

    def test_link_inside_nested_list_hanging_indent(self):
        body = "- item one\n  - nested item\n    hanging [x](docs/c.md) indent\n"
        link = _link_by_href(_doc(body), "docs/c.md")
        assert link.body_line == 3
        _assert_dest_span_exact(body, link)

    def test_lazy_continuation_in_blockquote(self):
        body = "> quoted start\nlazy continuation [x](docs/d.md) no marker\n"
        link = _link_by_href(_doc(body), "docs/d.md")
        assert link.body_line == 2
        _assert_dest_span_exact(body, link)

    def test_link_split_across_two_source_lines(self):
        body = "A [split\nlink](docs/e.md) across lines.\n"
        link = _link_by_href(_doc(body), "docs/e.md")
        # Reported at the construct start line by convention.
        assert link.body_line == 1
        assert link.dest_body_line == 2
        _assert_dest_span_exact(body, link)

    def test_construct_after_code_span_with_path_like_text(self):
        body = "Use `docs/decoy.md` then see [x](docs/real.md) here.\n"
        link = _link_by_href(_doc(body), "docs/real.md")
        _assert_dest_span_exact(body, link)
        # The decoy inside the code span must not be a text segment.
        segs = [s.text for s in _doc(body).text_segments()]
        assert not any("decoy" in s for s in segs)

    def test_body_offset_by_frontmatter(self):
        body = "# Title\n\nSee [x](docs/f.md) here.\n"
        doc = _doc(body, line_offset=4)
        link = _link_by_href(doc, "docs/f.md")
        assert link.body_line == 3
        assert link.file_line == 7
        assert link.dest_file_line == 7

    def test_line_map_callable_composes(self):
        doc = _doc("See [x](docs/g.md).\n", line_map=lambda n: n + 100)
        link = _link_by_href(doc, "docs/g.md")
        assert link.file_line == 101

    def test_tab_indented_context_degrades_gracefully(self):
        # Tabs in block prefixes may defeat exact column recovery; the line
        # number must still be exact and columns must never be wrong.
        body = ">\tquoted [x](docs/h.md) tab\n"
        link = _link_by_href(_doc(body), "docs/h.md")
        assert link.body_line == 1
        if link.has_dest_span:
            _assert_dest_span_exact(body, link)


class TestLinks:
    def test_titled_link(self):
        body = 'A [t](docs/setup.md "My Title") link.\n'
        link = _link_by_href(_doc(body), "docs/setup.md")
        assert link.title == "My Title"
        _assert_dest_span_exact(body, link)

    def test_angle_bracket_destination(self):
        body = "A [t](<docs/space file.md>) link.\n"
        link = _link_by_href(_doc(body), "docs/space file.md")
        _assert_dest_span_exact(body, link)

    def test_image_is_included(self):
        body = "An ![alt](images/i.png) image.\n"
        link = _link_by_href(_doc(body), "images/i.png")
        assert link.is_image
        _assert_dest_span_exact(body, link)

    def test_reference_link_resolved_with_dest_span(self):
        body = "See [ref style][myref] link.\n\n[myref]: docs/ref.md\n"
        link = _link_by_href(_doc(body), "docs/ref.md")
        assert link.is_reference
        assert link.has_dest_span
        assert link.body_line == 1
        assert link.dest_body_line == 3
        _assert_dest_span_exact(body, link)

    def test_reference_link_shortcut(self):
        body = "See [docs/ref.md] for info.\n\n[docs/ref.md]: docs/ref.md\n"
        link = _link_by_href(_doc(body), "docs/ref.md")
        assert link.is_reference
        assert link.has_dest_span
        assert link.dest_body_line == 3
        _assert_dest_span_exact(body, link)

    def test_reference_link_angle_bracketed(self):
        body = "See [ref][r] link.\n\n[r]: <docs/ref.md>\n"
        link = _link_by_href(_doc(body), "docs/ref.md")
        assert link.is_reference
        assert link.has_dest_span
        assert link.dest_body_line == 3
        _assert_dest_span_exact(body, link)

    def test_autolink(self):
        body = "Go to <https://example.com/x.md> now.\n"
        links = _doc(body).links()
        assert len(links) == 1
        assert links[0].is_autolink
        assert links[0].href == "https://example.com/x.md"

    def test_link_text_concatenated(self):
        body = "A [two *em* words](docs/a.md) link.\n"
        link = _link_by_href(_doc(body), "docs/a.md")
        assert link.text == "two em words"

    def test_link_inside_fence_not_reported(self):
        body = "```\n[x](docs/fenced.md)\n```\n"
        assert _doc(body).links() == []

    def test_escaped_text_before_link_does_not_shift_columns(self):
        body = "Escaped \\*star\\* and AT&amp;T then [x](docs/i.md) link.\n"
        link = _link_by_href(_doc(body), "docs/i.md")
        _assert_dest_span_exact(body, link)


class TestCodeSpans:
    def test_span_includes_backticks(self):
        body = "Use `docs/a.md` here.\n"
        (span,) = _doc(body).code_spans()
        assert body.split("\n")[0][span.col_start : span.col_end] == "`docs/a.md`"
        assert span.content == "docs/a.md"

    def test_double_backtick_with_inner_tick(self):
        body = "A `` code ` tick `` span.\n"
        (span,) = _doc(body).code_spans()
        assert span.content == "code ` tick"
        raw = body.split("\n")[0][span.col_start : span.col_end]
        assert raw == "`` code ` tick ``"

    def test_multiline_code_span_has_no_columns(self):
        body = "A `code\nspan` over lines.\n"
        (span,) = _doc(body).code_spans()
        assert span.multiline
        assert span.col_start is None

    def test_span_is_exact_code_content(self):
        body = "Use `docs/a.md` and `run docs/b.md` here.\n"
        doc = _doc(body)
        exact = doc.code_spans()[0]
        content_start = exact.col_start + 1
        content_end = exact.col_end - 1
        assert doc.span_is_exact_code_content(1, content_start, content_end) is exact
        # A sub-span of the second code span's content is not exact.
        assert doc.span_is_exact_code_content(1, 25, 35) is None


class TestHeadings:
    def test_atx_and_setext(self):
        body = "# Top\n\nSetext heading\n===\n\n## Sub ##\n"
        headings = _doc(body).headings()
        assert [(h.body_line, h.level, h.setext) for h in headings] == [
            (1, 1, False),
            (3, 1, True),
            (6, 2, False),
        ]
        assert headings[1].text == "Setext heading"
        assert headings[2].text == "Sub"

    def test_heading_inside_fence_ignored(self):
        body = "```\n# not a heading\n```\n"
        assert _doc(body).headings() == []


class TestHtmlComments:
    def test_block_comment(self):
        body = "text\n\n<!-- skillsaw-disable foo -->\n\nmore\n"
        (comment,) = _doc(body).html_comments()
        assert comment.text.strip() == "skillsaw-disable foo"
        assert comment.body_line_start == 3
        assert comment.body_line_end == 3

    def test_multiline_block_comment(self):
        body = "<!--\nskillsaw-disable foo\n-->\n"
        (comment,) = _doc(body).html_comments()
        assert comment.body_line_start == 1
        assert comment.body_line_end == 3

    def test_inline_comment(self):
        body = "some text <!-- note --> more\n"
        (comment,) = _doc(body).html_comments()
        assert comment.text.strip() == "note"
        assert comment.body_line_start == 1

    def test_comment_inside_fence_not_reported(self):
        body = "```markdown\n<!-- skillsaw-disable foo -->\n```\n"
        assert _doc(body).html_comments() == []


class TestFences:
    def test_fenced_block(self):
        body = "before\n\n```yaml\nkey: val\n```\n\nafter\n"
        (fence,) = _doc(body).fences()
        assert fence.info == "yaml"
        assert fence.body_line_start == 3
        assert fence.body_line_end == 5
        assert not fence.indented

    def test_indented_code_block(self):
        body = "before\n\n    indented code\n\nafter\n"
        (fence,) = _doc(body).fences()
        assert fence.indented
        assert fence.body_line_start == 3


class TestProseLines:
    def test_line_count_always_preserved(self):
        body = "# T\n\n```\ncode\n```\n\n    indented\n\n<!-- c -->\ntext `code` end\n"
        doc = _doc(body)
        assert len(doc.prose_lines()) == len(body.split("\n"))
        assert doc.prose_text().count("\n") == body.count("\n")

    def test_fence_lines_blanked_including_delimiters(self):
        body = "a\n```\nsecret docs/x.md\n```\nb\n"
        texts = [t for _, t in _doc(body).prose_lines()]
        assert texts == ["a", "", "", "", "b", ""]

    def test_indented_code_blanked(self):
        body = "para\n\n    docs/hidden.md\n\nafter\n"
        texts = [t for _, t in _doc(body).prose_lines()]
        assert texts[2] == ""

    def test_html_comment_blanked_with_spaces(self):
        body = "before <!-- docs/x.md --> after\n"
        texts = [t for _, t in _doc(body).prose_lines()]
        assert texts[0] == "before " + " " * len("<!-- docs/x.md -->") + " after"

    def test_code_span_blanked_with_spaces(self):
        body = "use `docs/x.md` here\n"
        texts = [t for _, t in _doc(body).prose_lines()]
        assert texts[0] == "use " + " " * len("`docs/x.md`") + " here"
        assert len(texts[0]) == len(body.split("\n")[0])

    def test_cross_paragraph_stray_backticks_do_not_hide_content(self):
        # Legacy DOTALL inline-code regex blanked across paragraph
        # boundaries, which CommonMark never does.
        body = "stray ` tick\n\n[link](docs/nope.md)\n\nanother ` tick\n"
        texts = [t for _, t in _doc(body).prose_lines()]
        assert "[link](docs/nope.md)" in texts[2]

    def test_file_lines_respect_offset(self):
        doc = _doc("a\nb\n", line_offset=10)
        assert [fl for fl, _ in doc.prose_lines()] == [11, 12, 13]


class TestTextSegments:
    def test_link_text_marked_in_link(self):
        body = "see [docs/a.md](docs/a.md) and docs/b.md\n"
        segs = _doc(body).text_segments()
        in_link = [s for s in segs if s.in_link]
        assert len(in_link) == 1 and in_link[0].text == "docs/a.md"
        bare = [s for s in segs if not s.in_link and "docs/b.md" in s.text]
        assert len(bare) == 1
        line = body.split("\n")[0]
        assert line[bare[0].col_start : bare[0].col_end] == bare[0].text

    def test_reference_definition_line_has_no_segments(self):
        body = "[myref]: docs/ref.md\n"
        assert _doc(body).text_segments() == []


class TestSplice:
    def test_single_edit(self):
        content = "Backup docs/setup.md today.\n"
        out = splice(content, [(1, 7, 20, "[docs/setup.md](docs/setup.md)")])
        assert out == "Backup [docs/setup.md](docs/setup.md) today.\n"

    def test_multiple_edits_same_line_right_to_left(self):
        content = "a docs/x.md b docs/y.md c\n"
        out = splice(content, [(1, 2, 11, "X"), (1, 14, 23, "Y")])
        assert out == "a X b Y c\n"

    def test_edits_on_different_lines(self):
        content = "one docs/a.md\ntwo docs/b.md\n"
        out = splice(content, [(2, 4, 13, "B"), (1, 4, 13, "A")])
        assert out == "one A\ntwo B\n"

    def test_overlapping_edits_skipped(self):
        content = "abcdef\n"
        out = splice(content, [(1, 0, 4, "X"), (1, 2, 6, "Y")])
        # Right-most edit applied; the overlapping left edit is skipped.
        assert out == "abY\n"

    def test_out_of_range_edit_skipped(self):
        content = "short\n"
        assert splice(content, [(1, 0, 99, "X")]) == content
        assert splice(content, [(9, 0, 2, "X")]) == content

    def test_crlf_preserved(self):
        content = "Backup docs/x.md now.\r\nnext\r\n"
        out = splice(content, [(1, 7, 16, "X")])
        assert out == "Backup X now.\r\nnext\r\n"

    def test_no_edits_returns_content(self):
        assert splice("abc\n", []) == "abc\n"


class TestContentMapLocate:
    """The bisect-based ``locate`` (issue #318) must be identical to the old
    linear scan and must not scale super-linearly."""

    @staticmethod
    def _linear_locate(cmap, content_pos):
        entry = cmap.entries[0]
        for candidate in cmap.entries:
            if candidate[0] <= content_pos:
                entry = candidate
            else:
                break
        line_start, body_line0, raw_col = entry
        if raw_col is None:
            return body_line0, None
        return body_line0, raw_col + (content_pos - line_start)

    def test_matches_linear_scan(self):
        body = "\n".join(f"Line {i} has a ref src/file_{i}.py here." for i in range(200))
        content = body
        cmap = _ContentMap(body.split("\n"), 0, content)
        for pos in range(0, len(content) + 5):
            assert cmap.locate(pos) == self._linear_locate(cmap, pos), pos

    def test_offset_before_first_entry_clamps(self):
        cmap = _ContentMap(["only line"], 0, "only line")
        # A negative offset resolves to the first entry's line, never IndexError.
        body_line, _col = cmap.locate(-1)
        assert body_line == 0

    def test_scales_sub_quadratically(self):
        # A single large paragraph used to make locate O(n^2) (issue #318).
        # Building the map plus locating every line start must stay near-linear;
        # a generous ceiling still catches a quadratic regression.
        import time

        def elapsed(n):
            body = "\n".join(f"path src/file_{i}.py" for i in range(n))
            cmap = _ContentMap(body.split("\n"), 0, body)
            t = time.perf_counter()
            for start, _line, _col in cmap.entries:
                cmap.locate(start)
            return time.perf_counter() - t

        small = elapsed(2000)
        large = elapsed(8000)
        # 4x the lines under quadratic scaling would be ~16x the time; require
        # well under that so a reintroduced linear scan fails loudly.
        assert large < (small + 1e-4) * 8


class TestCrlf:
    def test_links_and_prose_with_crlf(self):
        body = "# T\r\n\r\nSee [x](docs/a.md) here.\r\n```\r\ncode\r\n```\r\n"
        doc = _doc(body)
        link = _link_by_href(doc, "docs/a.md")
        assert link.body_line == 3
        # Column span must be valid against the \r-stripped line text.
        line = body.split("\n")[2].rstrip("\r")
        assert line[link.dest_col_start : link.dest_col_end] == "docs/a.md"
        assert len(doc.prose_lines()) == len(body.split("\n"))


class TestParityWithLegacyStrip:
    """prose_text() must match the legacy strip output except for documented
    divergences:

    1. Indented code blocks are now blanked (legacy scanned them as prose).
    2. Inline code spans are now blanked with spaces.
    3. Cross-paragraph stray-backtick/comment spans are now scanned
       (legacy DOTALL regexes blanked across paragraph boundaries).
    4. Fences with >3 leading spaces in container contexts (lists/quotes)
       are now recognized as code.
    """

    # Reference copy of the legacy regex-based strip (removed from
    # content_analysis.py in the GH-284 migration), kept here so the parity
    # harness keeps comparing against the historical behaviour.
    _OPENING_FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})")
    _CLOSING_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")
    _HTML_COMMENT_LEGACY_RE = re.compile(r"<!--.*?-->", re.DOTALL)

    @classmethod
    def _legacy_strip(cls, text: str) -> str:
        lines = text.split("\n")
        result = []
        fence_char = None
        fence_len = 0
        in_fence = False
        for line in lines:
            if not in_fence:
                m = cls._OPENING_FENCE_RE.match(line)
                if m:
                    fence_char = m.group(2)[0]
                    fence_len = len(m.group(2))
                    in_fence = True
                    result.append("")
                else:
                    result.append(line)
            else:
                cm = cls._CLOSING_FENCE_RE.match(line)
                if cm and cm.group(1)[0] == fence_char and len(cm.group(1)) >= fence_len:
                    in_fence = False
                    fence_char = None
                    fence_len = 0
                result.append("")
        stripped = "\n".join(result)
        return cls._HTML_COMMENT_LEGACY_RE.sub(
            lambda m: re.sub(r"[^\n]", " ", m.group(0)), stripped
        )

    @staticmethod
    def _line_diff_explained(legacy_line: str, new_line: str) -> bool:
        if new_line == "":
            return True  # block-level blanking (indented code, container fences)
        if len(legacy_line) != len(new_line):
            return False
        new_blanks_more = all(n == l or n == " " for n, l in zip(new_line, legacy_line))
        legacy_blanks_more = all(l == n or l == " " for n, l in zip(new_line, legacy_line))
        return new_blanks_more or legacy_blanks_more

    @pytest.mark.parametrize(
        "md_file",
        sorted(
            str(p.relative_to(Path(__file__).parent / "fixtures"))
            for p in (Path(__file__).parent / "fixtures").rglob("*.md")
        ),
    )
    def test_parity_on_fixture(self, md_file):
        path = Path(__file__).parent / "fixtures" / md_file
        text = path.read_text(encoding="utf-8")
        legacy = self._legacy_strip(text).split("\n")
        new = MarkdownDoc(text).prose_text().split("\n")
        assert len(legacy) == len(new), f"line count diverged for {md_file}"
        for i, (legacy_line, new_line) in enumerate(zip(legacy, new), 1):
            if legacy_line != new_line:
                assert self._line_diff_explained(legacy_line, new_line), (
                    f"{md_file}:{i} unexplained divergence:\n"
                    f"  legacy: {legacy_line!r}\n  new:    {new_line!r}"
                )
