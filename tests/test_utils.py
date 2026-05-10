"""
Tests for builtin rule utilities (read_text, read_json, frontmatter_key_line, heading_line,
and centralized YAML line number functions).
"""

from pathlib import Path

from skillsaw.rules.builtin.utils import (
    read_text,
    read_json,
    frontmatter_key_line,
    heading_line,
    yaml_key_line,
    yaml_key_lines,
    yaml_line_map,
    yaml_node_line,
    yaml_key_line_after,
    yaml_nth_key_line,
    yaml_nth_list_item_key_line,
    _extract_frontmatter_text,
)


def test_read_text_returns_content(temp_dir):
    f = temp_dir / "hello.txt"
    f.write_text("hello world", encoding="utf-8")
    assert read_text(f) == "hello world"


def test_read_text_returns_none_on_missing(temp_dir):
    assert read_text(temp_dir / "missing.txt") is None


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
