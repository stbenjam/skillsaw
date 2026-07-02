"""
Tests for builtin rule utilities (read_text, read_json, frontmatter_key_line, heading_line,
and centralized YAML line number functions).
"""

from pathlib import Path

from skillsaw.rules.builtin.utils import (
    read_text,
    read_json,
    extract_section,
    frontmatter_key_line,
    heading_line,
    parse_frontmatter,
    yaml_key_line,
    yaml_key_lines,
    yaml_line_map,
    yaml_node_line,
    yaml_key_line_after,
    yaml_nth_key_line,
    yaml_nth_list_item_key_line,
    _extract_frontmatter_text,
)


def test_extract_section_lf():
    content = "# T\n\n## Build\nrun make\n\n## Other\nx\n"
    assert extract_section(content, "Build") == "run make"


def test_extract_section_crlf():
    """CRLF content must resolve the section the same as LF (§1.14)."""
    content = "# T\r\n\r\n## Build\r\nrun make\r\n\r\n## Other\r\nx\r\n"
    assert extract_section(content, "Build") == "run make"


def test_extract_section_missing_returns_empty():
    assert extract_section("# T\n\n## Build\nrun\n", "Nope") == ""


def test_read_text_returns_content(temp_dir):
    f = temp_dir / "hello.txt"
    f.write_text("hello world", encoding="utf-8")
    assert read_text(f) == "hello world"


def test_read_text_returns_none_on_missing(temp_dir):
    assert read_text(temp_dir / "missing.txt") is None


def test_read_text_strips_utf8_bom(temp_dir):
    """A leading UTF-8 BOM must not survive into the returned text, else
    ``startswith('---')`` frontmatter detection breaks (issue #315)."""
    f = temp_dir / "bom.md"
    f.write_bytes(b"\xef\xbb\xbf---\nname: foo\n---\nbody\n")
    content = read_text(f)
    assert content is not None
    assert not content.startswith("\ufeff")
    assert content.startswith("---")


def test_write_text_preserving_keeps_crlf(temp_dir):
    """A CRLF file round-trips as CRLF even though the content is LF."""
    from skillsaw.utils import write_text_preserving, invalidate_read_caches

    f = temp_dir / "crlf.md"
    f.write_bytes(b"one\r\ntwo\r\n")
    invalidate_read_caches()
    # Content the fix engine produces is always LF-normalized.
    write_text_preserving(f, "one\r\nEDITED\r\n".replace("\r\n", "\n"))
    raw = f.read_bytes()
    assert raw == b"one\r\nEDITED\r\n"


def test_write_text_preserving_keeps_lf(temp_dir):
    """An LF file stays LF (no spurious CRLF introduced)."""
    from skillsaw.utils import write_text_preserving

    f = temp_dir / "lf.md"
    f.write_bytes(b"one\ntwo\n")
    write_text_preserving(f, "one\nEDITED\n")
    assert f.read_bytes() == b"one\nEDITED\n"


def test_write_text_preserving_restores_bom(temp_dir):
    """A file that had a BOM keeps it; content is passed BOM-free."""
    from skillsaw.utils import write_text_preserving

    f = temp_dir / "bom.md"
    f.write_bytes(b"\xef\xbb\xbf---\nname: foo\n---\n")
    write_text_preserving(f, "---\nname: bar\n---\n")
    raw = f.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw == b"\xef\xbb\xbf---\nname: bar\n---\n"


def test_write_text_preserving_new_file_defaults_to_lf(temp_dir):
    """Writing a path that does not yet exist uses plain LF, no BOM."""
    from skillsaw.utils import write_text_preserving

    f = temp_dir / "new.md"
    write_text_preserving(f, "hello\nworld\n")
    assert f.read_bytes() == b"hello\nworld\n"


def test_write_text_preserving_no_double_bom(temp_dir):
    """If a fix path leaves a BOM in the content, the writer must not add a
    second one (idempotent BOM handling)."""
    from skillsaw.utils import write_text_preserving

    f = temp_dir / "dbom.md"
    f.write_bytes(b"\xef\xbb\xbfhello\n")
    # Caller's content still carries the BOM (read with plain utf-8).
    write_text_preserving(f, "\ufeffhello world\n")
    raw = f.read_bytes()
    assert raw == b"\xef\xbb\xbfhello world\n"
    assert raw.count(b"\xef\xbb\xbf") == 1


def test_write_text_preserving_bom_and_crlf(temp_dir):
    """BOM + CRLF are both restored together."""
    from skillsaw.utils import write_text_preserving

    f = temp_dir / "both.md"
    f.write_bytes(b"\xef\xbb\xbfone\r\ntwo\r\n")
    write_text_preserving(f, "one\nEDITED\n")
    assert f.read_bytes() == b"\xef\xbb\xbfone\r\nEDITED\r\n"


def test_write_text_preserving_mixed_endings_lf_dominant(temp_dir):
    """A single stray CRLF in an otherwise-LF file must not flip the whole
    file to CRLF — the DOMINANT line ending wins."""
    from skillsaw.utils import write_text_preserving, invalidate_read_caches

    f = temp_dir / "mixed.md"
    f.write_bytes(b"l1\nl2\nl3\nl4\nl5\nl6\nl7\nl8\nl9\nstray\r\n")
    invalidate_read_caches()
    write_text_preserving(f, "l1\nEDITED\nl3\nl4\nl5\nl6\nl7\nl8\nl9\nstray\n")
    raw = f.read_bytes()
    assert b"\r" not in raw
    assert raw == b"l1\nEDITED\nl3\nl4\nl5\nl6\nl7\nl8\nl9\nstray\n"


def test_write_text_preserving_mixed_endings_crlf_dominant(temp_dir):
    """Majority-CRLF files keep CRLF even with a stray bare LF."""
    from skillsaw.utils import write_text_preserving, invalidate_read_caches

    f = temp_dir / "mixedcrlf.md"
    f.write_bytes(b"l1\r\nl2\r\nl3\r\nstray\n")
    invalidate_read_caches()
    write_text_preserving(f, "l1\nEDITED\nl3\nstray\n")
    assert f.read_bytes() == b"l1\r\nEDITED\r\nl3\r\nstray\r\n"


def test_write_text_preserving_mixed_endings_tie_goes_to_lf(temp_dir):
    """An exact CRLF/LF tie normalizes to LF."""
    from skillsaw.utils import write_text_preserving, invalidate_read_caches

    f = temp_dir / "tie.md"
    f.write_bytes(b"a\r\nb\n")
    invalidate_read_caches()
    write_text_preserving(f, "a\nEDITED\n")
    assert f.read_bytes() == b"a\nEDITED\n"


def test_write_text_preserving_lone_cr_becomes_lf(temp_dir):
    """Classic-Mac lone-CR files normalize to LF (no CRLF majority)."""
    from skillsaw.utils import write_text_preserving, invalidate_read_caches

    f = temp_dir / "cr.md"
    f.write_bytes(b"one\rtwo\r")
    invalidate_read_caches()
    write_text_preserving(f, "one\nEDITED\n")
    assert f.read_bytes() == b"one\nEDITED\n"


def test_write_text_preserving_mixed_endings_idempotent(temp_dir):
    """Writing the same content twice through the mixed-ending path is stable."""
    from skillsaw.utils import write_text_preserving, invalidate_read_caches

    f = temp_dir / "idem.md"
    f.write_bytes(b"l1\nl2\nl3\nstray\r\n")
    invalidate_read_caches()
    write_text_preserving(f, "l1\nl2\nl3\nstray\n")
    first = f.read_bytes()
    invalidate_read_caches()
    write_text_preserving(f, "l1\nl2\nl3\nstray\n")
    assert f.read_bytes() == first


def test_read_json_parses_valid(temp_dir):
    f = temp_dir / "data.json"
    f.write_text('{"key": "value"}', encoding="utf-8")
    data, error = read_json(f)
    assert data == {"key": "value"}
    assert error is None


def test_read_json_returns_error_on_invalid(temp_dir):
    f = temp_dir / "bad.json"
    f.write_text("{not valid", encoding="utf-8")
    data, error = read_json(f)
    assert data is None
    assert error is not None


def test_read_json_returns_error_on_missing(temp_dir):
    data, error = read_json(temp_dir / "missing.json")
    assert data is None
    assert "Failed to read" in error


def test_frontmatter_key_line_finds_key(temp_dir):
    f = temp_dir / "doc.md"
    f.write_text("---\nname: test\ndescription: A thing\n---\n", encoding="utf-8")
    assert frontmatter_key_line(f, "name") == 2
    assert frontmatter_key_line(f, "description") == 3


def test_frontmatter_key_line_returns_none_for_missing_key(temp_dir):
    f = temp_dir / "doc.md"
    f.write_text("---\nname: test\n---\n", encoding="utf-8")
    assert frontmatter_key_line(f, "description") is None


def test_frontmatter_key_line_returns_none_without_frontmatter(temp_dir):
    f = temp_dir / "doc.md"
    f.write_text("# Just markdown\n", encoding="utf-8")
    assert frontmatter_key_line(f, "name") is None


def test_frontmatter_key_line_returns_none_on_missing_file(temp_dir):
    assert frontmatter_key_line(temp_dir / "nope.md", "name") is None


def test_frontmatter_key_line_ignores_keys_outside_frontmatter(temp_dir):
    f = temp_dir / "doc.md"
    f.write_text("---\ntitle: hello\n---\nname: not-in-frontmatter\n", encoding="utf-8")
    assert frontmatter_key_line(f, "name") is None
    assert frontmatter_key_line(f, "title") == 2


def test_heading_line_finds_heading(temp_dir):
    f = temp_dir / "doc.md"
    f.write_text("---\nfoo: bar\n---\n\n## Name\nSome content\n\n## Description\nMore\n")
    assert heading_line(f, "Name") == 5
    assert heading_line(f, "Description") == 8


def test_heading_line_returns_none_for_missing(temp_dir):
    f = temp_dir / "doc.md"
    f.write_text("## Name\nContent\n")
    assert heading_line(f, "Synopsis") is None


def test_heading_line_respects_level(temp_dir):
    f = temp_dir / "doc.md"
    f.write_text("# Top\n## Sub\n### Deep\n")
    assert heading_line(f, "Top", level=1) == 1
    assert heading_line(f, "Sub", level=2) == 2
    assert heading_line(f, "Deep", level=3) == 3
    assert heading_line(f, "Top", level=2) is None


def test_heading_line_returns_none_on_missing_file(temp_dir):
    assert heading_line(temp_dir / "nope.md", "Name") is None


# ---------------------------------------------------------------------------
# _extract_frontmatter_text
# ---------------------------------------------------------------------------


def test_extract_frontmatter_text_basic():
    content = "---\nname: test\ndescription: A thing\n---\nbody\n"
    text, offset = _extract_frontmatter_text(content)
    assert text == "name: test\ndescription: A thing\n"
    assert offset == 1


def test_extract_frontmatter_text_no_frontmatter():
    content = "# Just markdown\n"
    text, offset = _extract_frontmatter_text(content)
    assert text is None
    assert offset == 0


# ---------------------------------------------------------------------------
# yaml_key_line
# ---------------------------------------------------------------------------


def test_yaml_key_line_top_level():
    text = "name: test\ndescription: A thing\n"
    assert yaml_key_line(text, "name", top_level=True) == 1
    assert yaml_key_line(text, "description", top_level=True) == 2


def test_yaml_key_line_nested():
    text = "metadata:\n  openclaw:\n    always: true\n"
    assert yaml_key_line(text, "always") == 3
    assert yaml_key_line(text, "always", top_level=True) is None


def test_yaml_key_line_with_offset():
    text = "name: test\n"
    assert yaml_key_line(text, "name", top_level=True, line_offset=1) == 2


def test_yaml_key_line_missing():
    text = "name: test\n"
    assert yaml_key_line(text, "missing") is None


def test_yaml_key_line_invalid_yaml():
    text = ":\n  bad: [unterminated\n"
    assert yaml_key_line(text, "bad") is None


def test_yaml_key_line_quoted_value_with_colon():
    """Quoted values containing colons should not confuse the parser."""
    text = 'url: "http://example.com:8080"\nname: test\n'
    assert yaml_key_line(text, "name", top_level=True) == 2


def test_yaml_key_line_multiline_string():
    """Multiline strings should not confuse line tracking."""
    text = "description: |\n  line one\n  line two\nname: test\n"
    assert yaml_key_line(text, "name", top_level=True) == 4


def test_yaml_key_line_anchor():
    """YAML anchors should not confuse the parser."""
    text = "defaults: &defaults\n  color: blue\ntheme:\n  <<: *defaults\n  name: dark\n"
    assert yaml_key_line(text, "name") == 5


# ---------------------------------------------------------------------------
# yaml_key_lines
# ---------------------------------------------------------------------------


def test_yaml_key_lines_multiple_occurrences():
    text = (
        "reviews:\n"
        "  instructions: Do stuff.\n"
        "  tools:\n"
        "    biome:\n"
        "      instructions: Use biome.\n"
        "chat:\n"
        "  instructions: Be helpful.\n"
    )
    lines = yaml_key_lines(text, "instructions")
    assert lines == [2, 5, 7]


def test_yaml_key_lines_none_found():
    text = "name: test\n"
    assert yaml_key_lines(text, "missing") == []


def test_yaml_key_lines_invalid_yaml():
    assert yaml_key_lines(":\n  bad: [unterminated\n", "bad") == []


# ---------------------------------------------------------------------------
# yaml_line_map
# ---------------------------------------------------------------------------


def test_yaml_line_map_flat():
    text = "name: test\ndescription: A thing\n"
    result = yaml_line_map(text)
    assert result["name"] == 1
    assert result["description"] == 2


def test_yaml_line_map_nested():
    text = "metadata:\n  openclaw:\n    always: true\n    os:\n      - darwin\n"
    result = yaml_line_map(text)
    assert result["metadata"] == 1
    assert result["openclaw"] == 2
    assert result["always"] == 3
    assert result["os"] == 4


def test_yaml_line_map_with_offset():
    text = "name: test\n"
    result = yaml_line_map(text, line_offset=1)
    assert result["name"] == 2


def test_yaml_line_map_invalid_yaml():
    assert yaml_line_map(":\n  bad: [unterminated\n") == {}


def test_yaml_line_map_duplicate_keys_last_wins():
    """When a key name appears at multiple nesting levels, last occurrence wins."""
    text = "bins:\n  - foo\nrequires:\n  bins:\n    - bar\n"
    result = yaml_line_map(text)
    # The second 'bins' at line 4 should overwrite the first at line 1
    assert result["bins"] == 4


# ---------------------------------------------------------------------------
# yaml_node_line
# ---------------------------------------------------------------------------


def test_yaml_node_line_dotted_path():
    text = "metadata:\n  openclaw:\n    os:\n      - darwin\n"
    assert yaml_node_line(text, "metadata.openclaw.os") == 3


def test_yaml_node_line_top_level():
    text = "name: test\n"
    assert yaml_node_line(text, "name") == 1


def test_yaml_node_line_with_list_index():
    text = "install:\n  - id: brew\n    kind: brew\n  - id: npm\n    kind: node\n"
    assert yaml_node_line(text, "install[1].kind") == 5


def test_yaml_node_line_missing_path():
    text = "name: test\n"
    assert yaml_node_line(text, "metadata.openclaw.os") is None


def test_yaml_node_line_invalid_yaml():
    assert yaml_node_line(":\n  bad: [unterminated\n", "bad") is None


# ---------------------------------------------------------------------------
# yaml_key_line_after
# ---------------------------------------------------------------------------


def test_yaml_key_line_after_basic():
    text = "reviews:\n" "  instructions: Do stuff.\n" "chat:\n" "  instructions: Be helpful.\n"
    assert yaml_key_line_after(text, "instructions", 1) == 2
    assert yaml_key_line_after(text, "instructions", 2) == 4
    assert yaml_key_line_after(text, "instructions", 4) is None


# ---------------------------------------------------------------------------
# yaml_nth_key_line
# ---------------------------------------------------------------------------


def test_yaml_nth_key_line_basic():
    text = (
        "reviews:\n"
        "  instructions: A.\n"
        "  tools:\n"
        "    biome:\n"
        "      instructions: B.\n"
        "chat:\n"
        "  instructions: C.\n"
    )
    assert yaml_nth_key_line(text, "instructions", 0) == 2
    assert yaml_nth_key_line(text, "instructions", 1) == 5
    assert yaml_nth_key_line(text, "instructions", 2) == 7
    assert yaml_nth_key_line(text, "instructions", 3) is None


# ---------------------------------------------------------------------------
# yaml_nth_list_item_key_line
# ---------------------------------------------------------------------------


def test_yaml_nth_list_item_key_line_basic():
    text = (
        "custom_checks:\n"
        "  - name: Check A\n"
        "    instructions: Do A.\n"
        "  - name: Check B\n"
        "    instructions: Do B.\n"
    )
    assert yaml_nth_list_item_key_line(text, "name", 0) == 2
    assert yaml_nth_list_item_key_line(text, "name", 1) == 4
    assert yaml_nth_list_item_key_line(text, "name", 2) is None


def test_yaml_nth_list_item_key_line_after_line():
    text = "items:\n" "  - name: A\n" "  - name: B\n" "checks:\n" "  - name: C\n" "  - name: D\n"
    # Only items after line 3
    assert yaml_nth_list_item_key_line(text, "name", 0, after_line=3) == 5
    assert yaml_nth_list_item_key_line(text, "name", 1, after_line=3) == 6


# ---------------------------------------------------------------------------
# Edge cases for YAML parsing robustness
# ---------------------------------------------------------------------------


def test_yaml_key_line_with_comments():
    """Comments in YAML should not affect line tracking."""
    text = "# A comment\nname: test  # inline comment\ndescription: A thing\n"
    assert yaml_key_line(text, "name", top_level=True) == 2
    assert yaml_key_line(text, "description", top_level=True) == 3


def test_yaml_key_line_with_empty_value():
    text = "name:\ndescription: A thing\n"
    assert yaml_key_line(text, "name", top_level=True) == 1


def test_yaml_key_line_flow_mapping():
    """Flow-style mappings should be handled."""
    text = "metadata: {version: '1.0', author: test}\nname: foo\n"
    assert yaml_key_line(text, "name", top_level=True) == 2
    assert yaml_key_line(text, "metadata", top_level=True) == 1


def test_parse_frontmatter_valid():
    content = "---\nname: test\ndescription: hello\n---\n# Body\n"
    fm, body, error_line = parse_frontmatter(content)
    assert fm == {"name": "test", "description": "hello"}
    assert "# Body" in body
    assert error_line is None


def test_parse_frontmatter_malformed_yaml_reports_error_line():
    content = "---\nname: test\nversion: 1.0\nbad_yaml: [unclosed\n---\n"
    fm, body, error_line = parse_frontmatter(content)
    assert fm is None
    assert error_line is not None
    assert error_line == 5  # --- closing line where parser fails


def test_parse_frontmatter_no_frontmatter():
    content = "# Just a heading\nSome text\n"
    fm, body, error_line = parse_frontmatter(content)
    assert fm is None
    assert error_line is None
    assert body == content


def test_parse_frontmatter_bogus_closing_delimiter():
    """Closing delimiter with trailing non-whitespace (e.g. ---BOGUS) must not match."""
    content = "---\nname: test\n---BOGUS\n# Body\n"
    fm, body, error_line = parse_frontmatter(content)
    assert fm is None
    assert error_line is None
    assert body == content


def test_extract_frontmatter_text_bogus_closing_delimiter():
    """_extract_frontmatter_text must reject ---BOGUS as a closing delimiter."""
    content = "---\nname: test\n---BOGUS\n# Body\n"
    text, offset = _extract_frontmatter_text(content)
    assert text is None


def test_parse_frontmatter_bogus_closing_delimiter_with_whitespace():
    """Closing delimiter with whitespace then non-whitespace (e.g. '--- BOGUS') must not match."""
    content = "---\nname: test\n--- BOGUS\n# Body\n"
    fm, body, error_line = parse_frontmatter(content)
    assert fm is None
    assert error_line is None
    assert body == content


def test_parse_frontmatter_trailing_whitespace_on_closing_delimiter():
    """Closing delimiter with only trailing whitespace ('---   ') should still match."""
    content = "---\nname: test\n---   \n# Body\n"
    fm, body, error_line = parse_frontmatter(content)
    assert fm == {"name": "test"}
    assert error_line is None


def test_parse_frontmatter_closing_at_eof_without_newline():
    """Closing --- at end of string with no trailing newline should still match."""
    content = "---\nname: test\n---"
    fm, body, error_line = parse_frontmatter(content)
    assert fm == {"name": "test"}
    assert error_line is None


class TestFrontmatterHelpers:
    """Shared frontmatter regex + insertion helpers (GH-284 consolidation)."""

    def test_frontmatter_text(self):
        from skillsaw.rules.builtin.utils import frontmatter_text

        assert frontmatter_text("---\nname: x\n---\nbody\n") == "name: x\n"
        assert frontmatter_text("no frontmatter\n") is None

    def test_frontmatter_text_crlf(self):
        from skillsaw.rules.builtin.utils import frontmatter_text

        assert frontmatter_text("---\r\nname: x\r\n---\r\nbody\r\n") == "name: x\r\n"

    def test_insert_frontmatter_fields(self):
        from skillsaw.rules.builtin.utils import insert_frontmatter_fields

        out = insert_frontmatter_fields("---\nname: x\n---\nbody\n", ["description: "])
        assert out == "---\nname: x\ndescription: \n---\nbody\n"

    def test_insert_frontmatter_fields_crlf(self):
        from skillsaw.rules.builtin.utils import insert_frontmatter_fields

        out = insert_frontmatter_fields("---\r\nname: x\r\n---\r\nbody\r\n", ["description: "])
        assert out == "---\r\nname: x\r\ndescription: \r\n---\r\nbody\r\n"

    def test_prepend_frontmatter_fields(self):
        from skillsaw.rules.builtin.utils import prepend_frontmatter_fields

        out = prepend_frontmatter_fields("---\ndescription: d\n---\nbody\n", ["name: x"])
        assert out == "---\nname: x\ndescription: d\n---\nbody\n"

    def test_parse_frontmatter_crlf(self):
        from skillsaw.rules.builtin.utils import parse_frontmatter

        fm, body, err = parse_frontmatter("---\r\nname: x\r\n---\r\nbody text\r\n")
        assert err is None
        assert fm == {"name": "x"}
        assert body == "body text\r\n"


class TestReplaceFrontmatterField:
    """replace_frontmatter_field must only splice genuine top-level keys and
    never orphan continuation lines (agentskill-valid SAFE-fix corruption)."""

    def test_replaces_single_line_value(self):
        from skillsaw.rules.builtin.utils import replace_frontmatter_field

        out = replace_frontmatter_field("---\nname: old\nd: x\n---\nbody\n", "name", "name: new")
        assert out == "---\nname: new\nd: x\n---\nbody\n"

    def test_replaces_empty_null_value_in_place(self):
        """An empty/null value still has a ``name:`` key line — replacing it
        in place (not prepending a duplicate) is the issue #321 invariant."""
        from skillsaw.rules.builtin.utils import replace_frontmatter_field

        out = replace_frontmatter_field("---\nname:\nd: x\n---\n", "name", "name: new")
        assert out == "---\nname: new\nd: x\n---\n"
        out = replace_frontmatter_field('---\nname: ""\nd: x\n---\n', "name", "name: new")
        assert out == "---\nname: new\nd: x\n---\n"

    def test_missing_key_returns_none(self):
        from skillsaw.rules.builtin.utils import replace_frontmatter_field

        assert replace_frontmatter_field("---\nd: x\n---\n", "name", "name: new") is None

    def test_no_frontmatter_returns_none(self):
        from skillsaw.rules.builtin.utils import replace_frontmatter_field

        assert replace_frontmatter_field("# heading\n", "name", "name: new") is None

    def test_multiline_falsy_value_replaced_without_orphaned_continuation(self):
        """``name:\\n  []`` — replacing only the key line used to orphan the
        ``[]`` continuation line, corrupting the value.  The whole value
        span must be replaced instead."""
        from skillsaw.rules.builtin.utils import replace_frontmatter_field, parse_frontmatter

        content = "---\nname:\n  []\ndescription: d\n---\nbody\n"
        out = replace_frontmatter_field(content, "name", "name: my-skill")
        assert out == "---\nname: my-skill\ndescription: d\n---\nbody\n"
        fm, _body, err = parse_frontmatter(out)
        assert err is None
        assert fm == {"name": "my-skill", "description": "d"}

    def test_flow_mapping_continuation_line_not_replaced(self):
        """A column-0 continuation line of a flow mapping matches a naive
        ``^name:`` regex but is NOT a top-level key — replacing it destroyed
        the closing ``}`` and made valid frontmatter unparseable."""
        from skillsaw.rules.builtin.utils import replace_frontmatter_field, parse_frontmatter

        content = "---\nmetadata: {tags: [x],\nname: legacy-tag}\ndescription: d\n---\nbody\n"
        out = replace_frontmatter_field(content, "name", "name: my-skill")
        # No genuine top-level ``name`` key: callers fall back to inserting
        # the field, which is safe here.
        assert out is None
        # The documented fallback path must produce valid YAML.
        from skillsaw.rules.builtin.utils import prepend_frontmatter_fields

        fixed = prepend_frontmatter_fields(content, ["name: my-skill"])
        fm, _body, err = parse_frontmatter(fixed)
        assert err is None
        assert fm["name"] == "my-skill"
        assert fm["metadata"] == {"tags": ["x"], "name": "legacy-tag"}

    def test_block_scalar_value_fully_replaced(self):
        from skillsaw.rules.builtin.utils import replace_frontmatter_field

        content = "---\nname: >-\n  Foo Bar\nd: x\n---\n"
        out = replace_frontmatter_field(content, "name", "name: new")
        assert out == "---\nname: new\nd: x\n---\n"

    def test_multiline_plain_scalar_fully_replaced(self):
        from skillsaw.rules.builtin.utils import replace_frontmatter_field

        content = "---\nname: foo\n  bar\nd: x\n---\n"
        out = replace_frontmatter_field(content, "name", "name: new")
        assert out == "---\nname: new\nd: x\n---\n"

    def test_crlf_multiline_value(self):
        from skillsaw.rules.builtin.utils import replace_frontmatter_field

        content = "---\r\nname:\r\n  []\r\nd: x\r\n---\r\n"
        out = replace_frontmatter_field(content, "name", "name: new")
        assert out == "---\r\nname: new\r\nd: x\r\n---\r\n"

    def test_flow_style_top_level_mapping_is_noop(self):
        """A flow-style top-level mapping has no key *line* to splice —
        the content must come back untouched rather than corrupted."""
        from skillsaw.rules.builtin.utils import replace_frontmatter_field

        content = "---\n{name: x, d: y}\n---\n"
        assert replace_frontmatter_field(content, "name", "name: new") == content

    def test_duplicate_keys_are_noop(self):
        """Duplicate top-level keys are undeterminable (ruamel rejects them);
        the content must come back untouched rather than half-replaced."""
        from skillsaw.rules.builtin.utils import replace_frontmatter_field

        content = "---\nname: a\nname: b\n---\n"
        assert replace_frontmatter_field(content, "name", "name: new") == content
