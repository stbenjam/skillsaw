"""
Tests for builtin rule utilities (read_text, read_json, frontmatter_key_line, heading_line,
and centralized YAML line number functions).
"""

import os
from pathlib import Path
import stat
import sys

import yaml

import pytest

from skillsaw import utils as skillsaw_utils
from skillsaw.utils import mkdir_parents_anchored, rename_path_anchored, write_bytes_atomic

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
    yaml_path_line_lookup,
    yaml_key_line_after,
    yaml_nth_key_line,
    yaml_nth_list_item_key_line,
    _extract_frontmatter_text,
)


def test_extract_section_lf():
    content = "# T\n\n## Build\nrun make\n\n## Other\nx\n"
    assert extract_section(content, "Build") == "run make"


def test_atomic_write_preserves_existing_mode(tmp_path):
    target = tmp_path / "artifact.json"
    target.write_bytes(b"old")
    target.chmod(0o640)

    write_bytes_atomic(target, b"new")

    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_atomic_write_new_file_remains_private_with_restrictive_umask(tmp_path):
    target = tmp_path / "artifact.json"
    previous_umask = os.umask(0o027)
    try:
        write_bytes_atomic(target, b"new")
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_atomic_write_new_file_is_not_world_writable_with_permissive_umask(tmp_path):
    target = tmp_path / "artifact.json"
    previous_umask = os.umask(0)
    try:
        write_bytes_atomic(target, b"new")
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_atomic_write_rejects_symlinked_parent_outside_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    redirected = root / "redirected"
    redirected.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match=r"symlinked directory|escapes root"):
        write_bytes_atomic(redirected / "artifact.json", b"new", root=root)

    assert not (outside / "artifact.json").exists()


@pytest.mark.skipif(
    not skillsaw_utils._supports_anchored_atomic_write(),
    reason="descriptor-relative rename is unavailable",
)
def test_anchored_rename_moves_a_contained_file(tmp_path):
    source = tmp_path / "source.md"
    destination = tmp_path / "destination.md"
    source.write_text("content", encoding="utf-8")

    rename_path_anchored(source, destination, root=tmp_path)

    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "content"


@pytest.mark.skipif(
    not skillsaw_utils._supports_anchored_atomic_write(),
    reason="descriptor-relative rename is unavailable",
)
def test_anchored_rename_rejects_existing_destination(tmp_path):
    source = tmp_path / "source.md"
    destination = tmp_path / "destination.md"
    source.write_text("source", encoding="utf-8")
    destination.write_text("destination", encoding="utf-8")

    with pytest.raises(FileExistsError, match=r"Rename destination already exists"):
        rename_path_anchored(source, destination, root=tmp_path)

    assert source.read_text(encoding="utf-8") == "source"
    assert destination.read_text(encoding="utf-8") == "destination"


@pytest.mark.skipif(
    not skillsaw_utils._supports_anchored_atomic_write(),
    reason="descriptor-relative rename is unavailable",
)
def test_anchored_rename_rejects_symlink_endpoints(tmp_path):
    victim = tmp_path / "victim.md"
    victim.write_text("victim", encoding="utf-8")

    source_link = tmp_path / "source-link.md"
    source_link.symlink_to(victim)
    with pytest.raises(OSError, match=r"Refusing to rename symlink"):
        rename_path_anchored(source_link, tmp_path / "destination.md", root=tmp_path)

    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    destination_link = tmp_path / "destination-link.md"
    destination_link.symlink_to(victim)
    with pytest.raises(OSError, match=r"Refusing to rename over symlink"):
        rename_path_anchored(source, destination_link, root=tmp_path)

    assert source.read_text(encoding="utf-8") == "source"
    assert victim.read_text(encoding="utf-8") == "victim"


@pytest.mark.skipif(
    not skillsaw_utils._supports_anchored_atomic_write(),
    reason="descriptor-relative rename is unavailable",
)
def test_anchored_rename_allows_same_inode_destination(tmp_path):
    source = tmp_path / "source.md"
    destination = tmp_path / "destination.md"
    source.write_text("content", encoding="utf-8")
    os.link(source, destination)

    rename_path_anchored(source, destination, root=tmp_path)

    assert source.samefile(destination)
    assert source.read_text(encoding="utf-8") == "content"
    assert destination.read_text(encoding="utf-8") == "content"


def test_anchored_mkdir_creates_missing_directory_tree(tmp_path):
    destination = tmp_path / "nested" / "deeper"

    mkdir_parents_anchored(destination, root=tmp_path)

    assert destination.is_dir()


def test_anchored_mkdir_rejects_symlinked_parent(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    redirected = tmp_path / "redirected"
    redirected.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match=r"symlinked directory|escapes root"):
        mkdir_parents_anchored(redirected / "nested", root=tmp_path)

    assert list(outside.iterdir()) == []


def test_anchored_mkdir_fallback_creates_missing_tree(tmp_path, monkeypatch):
    destination = tmp_path / "nested" / "deeper"
    monkeypatch.setattr("skillsaw.utils._supports_anchored_atomic_write", lambda: False)

    mkdir_parents_anchored(destination, root=tmp_path)

    assert destination.is_dir()


def test_anchored_rename_uses_validated_fallback_on_unsupported_platform(tmp_path, monkeypatch):
    source = tmp_path / "source.md"
    destination = tmp_path / "destination.md"
    source.write_text("content", encoding="utf-8")
    monkeypatch.setattr("skillsaw.utils._supports_anchored_atomic_write", lambda: False)

    rename_path_anchored(source, destination, root=tmp_path)

    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "content"


def test_anchored_rename_fallback_rejects_symlink_destination(tmp_path, monkeypatch):
    source = tmp_path / "source.md"
    destination = tmp_path / "destination.md"
    victim = tmp_path / "victim.md"
    source.write_text("content", encoding="utf-8")
    victim.write_text("victim", encoding="utf-8")
    destination.symlink_to(victim)
    monkeypatch.setattr("skillsaw.utils._supports_anchored_atomic_write", lambda: False)

    with pytest.raises(OSError, match=r"Refusing to rename over symlink|escapes root"):
        rename_path_anchored(source, destination, root=tmp_path)

    assert source.read_text(encoding="utf-8") == "content"
    assert victim.read_text(encoding="utf-8") == "victim"


def test_anchored_rename_fallback_rejects_symlink_source(tmp_path, monkeypatch):
    victim = tmp_path / "victim.md"
    source = tmp_path / "source.md"
    destination = tmp_path / "destination.md"
    victim.write_text("victim", encoding="utf-8")
    source.symlink_to(victim)
    monkeypatch.setattr("skillsaw.utils._supports_anchored_atomic_write", lambda: False)

    with pytest.raises(OSError, match=r"Refusing to rename symlink"):
        rename_path_anchored(source, destination, root=tmp_path)

    assert victim.read_text(encoding="utf-8") == "victim"
    assert not destination.exists()


def test_anchored_rename_fallback_rejects_existing_destination(tmp_path, monkeypatch):
    source = tmp_path / "source.md"
    destination = tmp_path / "destination.md"
    source.write_text("source", encoding="utf-8")
    destination.write_text("destination", encoding="utf-8")
    monkeypatch.setattr("skillsaw.utils._supports_anchored_atomic_write", lambda: False)

    with pytest.raises(FileExistsError, match=r"Rename destination already exists"):
        rename_path_anchored(source, destination, root=tmp_path)

    assert source.read_text(encoding="utf-8") == "source"
    assert destination.read_text(encoding="utf-8") == "destination"


def test_anchored_rename_fallback_allows_same_inode_destination(tmp_path, monkeypatch):
    source = tmp_path / "source.md"
    destination = tmp_path / "destination.md"
    source.write_text("content", encoding="utf-8")
    os.link(source, destination)
    monkeypatch.setattr("skillsaw.utils._supports_anchored_atomic_write", lambda: False)

    rename_path_anchored(source, destination, root=tmp_path)

    assert source.samefile(destination)
    assert source.read_text(encoding="utf-8") == "content"
    assert destination.read_text(encoding="utf-8") == "content"


def test_atomic_write_preserves_mode_without_fchmod(tmp_path, monkeypatch):
    target = tmp_path / "artifact.json"
    target.write_bytes(b"old")
    target.chmod(0o640)
    monkeypatch.delattr(os, "fchmod", raising=False)

    write_bytes_atomic(target, b"new")

    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_atomic_write_does_not_close_reused_fd_after_replace_failure(tmp_path, monkeypatch):
    target = tmp_path / "artifact.json"
    replacement = tmp_path / "replacement.txt"
    temporary_fd = None
    reused_fd = None
    real_fdopen = os.fdopen

    def track_temporary_fd(fd, *args, **kwargs):
        nonlocal temporary_fd
        temporary_fd = fd
        return real_fdopen(fd, *args, **kwargs)

    def fail_after_reusing_fd(_source, _destination):
        nonlocal reused_fd
        assert temporary_fd is not None
        candidate_fd = os.open(replacement, os.O_WRONLY | os.O_CREAT, 0o600)
        if candidate_fd != temporary_fd:
            os.dup2(candidate_fd, temporary_fd)
            os.close(candidate_fd)
        reused_fd = temporary_fd
        raise OSError("replace failed")

    monkeypatch.setattr(os, "fdopen", track_temporary_fd)
    monkeypatch.setattr(os, "replace", fail_after_reusing_fd)

    with pytest.raises(OSError, match="replace failed"):
        write_bytes_atomic(target, b"new")

    assert reused_fd is not None
    try:
        os.write(reused_fd, b"still open")
    finally:
        os.close(reused_fd)


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


def test_write_text_preserving_refuses_symlink_target(temp_dir):
    from skillsaw.utils import write_text_preserving

    victim = temp_dir / "victim.md"
    victim.write_text("original\n")
    target = temp_dir / "target.md"
    target.symlink_to(victim)

    with pytest.raises(OSError, match="Refusing to write through symlink"):
        write_text_preserving(target, "changed\n", root=temp_dir)

    assert victim.read_text() == "original\n"


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


def test_yaml_line_map_merge_key_in_list_entry_no_crash():
    """Merge-derived keys ('<<: *anchor') have no position in the merged
    mapping; ruamel raises KeyError for them.  They must be skipped, not
    crash the whole line map (issue: openclaw-metadata rule-execution-error)."""
    text = (
        "anchors:\n"  # 1
        "  - &base\n"  # 2
        "    kind: brew\n"  # 3
        "    formula: rg\n"  # 4
        "metadata:\n"  # 5
        "  openclaw:\n"  # 6
        "    install:\n"  # 7
        "      - <<: *base\n"  # 8
        "        id: two\n"  # 9
    )
    result = yaml_line_map(text)
    # Real keys keep their lines; 'kind'/'formula' come from the anchor's
    # own mapping, and the merge-derived copies in install[0] are skipped.
    assert result["id"] == 9
    assert result["kind"] == 3
    assert result["metadata"] == 5


def test_yaml_line_map_merge_key_in_mapping_no_crash():
    text = (
        "defaults: &defaults\n"  # 1
        "  category: productivity\n"  # 2
        "metadata:\n"  # 3
        "  openclaw:\n"  # 4
        "    <<: *defaults\n"  # 5
        "    always: true\n"  # 6
    )
    result = yaml_line_map(text)
    assert result["always"] == 6
    assert result["category"] == 2


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


def test_yaml_node_line_merge_derived_key_returns_none():
    """A key reachable only through '<<: *anchor' has no line of its own —
    return None (omit the line) instead of raising KeyError."""
    text = (
        "anchors:\n"
        "  - &base\n"
        "    kind: brew\n"
        "    formula: rg\n"
        "metadata:\n"
        "  openclaw:\n"
        "    install:\n"
        "      - <<: *base\n"
        "        id: two\n"
    )
    assert yaml_node_line(text, "metadata.openclaw.install[0].kind") is None
    # Non-merge siblings still resolve
    assert yaml_node_line(text, "metadata.openclaw.install[0].id") == 9


# ---------------------------------------------------------------------------
# yaml_path_line_lookup
# ---------------------------------------------------------------------------


def test_yaml_path_line_lookup_resolves_multiple_paths():
    text = "install:\n  - id: a\n    kind: node\n  - id: b\n    kind: brew\n"
    lookup = yaml_path_line_lookup(text)
    assert lookup("install[0].kind") == 3
    assert lookup("install[1].kind") == 5
    assert lookup("install[2].kind") is None
    assert lookup("missing.path") is None


def test_yaml_path_line_lookup_with_offset():
    lookup = yaml_path_line_lookup("name: test\n", line_offset=1)
    assert lookup("name") == 2


def test_yaml_path_line_lookup_invalid_yaml():
    lookup = yaml_path_line_lookup(":\n  bad: [unterminated\n")
    assert lookup("bad") is None


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


def test_parse_frontmatter_recursion_is_reported_as_invalid():
    nested = "[" * 1200 + "0" + "]" * 1200
    content = f"---\nextra: {nested}\n---\nbody\n"
    frontmatter, body, error_line = parse_frontmatter(content)

    assert frontmatter is None
    assert body == content
    assert error_line is None


def test_safe_load_yaml_rejects_pathological_nesting():
    """The depth limit is stated, not inherited from CPython's stack.

    Which document overflows the interpreter varies by platform, thread
    stack size and Python version, so the reader enforces the bound
    itself rather than relying on one.
    """
    from skillsaw.utils import _MAX_YAML_DEPTH, safe_load_yaml

    depth = _MAX_YAML_DEPTH + 5
    with pytest.raises(RecursionError):
        safe_load_yaml("[" * depth + "0" + "]" * depth)


@pytest.mark.parametrize("offset, accepted", [(-2, True), (-1, False), (0, False)])
def test_the_depth_bound_sits_where_it_says_it_does(offset, accepted):
    """Both sides of the boundary, not just the rejecting one.

    The bound replaced an incidental limit far above it, so only ever
    testing rejection would let it drift down onto documents that parse
    today — the direction that breaks people rather than protects them.
    The document is a mapping wrapping a chain of sequences, so its
    container count is ``depth + 1``.
    """
    from skillsaw.utils import _MAX_YAML_DEPTH, safe_load_yaml

    depth = _MAX_YAML_DEPTH + offset
    source = "extra: " + "[" * depth + "0" + "]" * depth

    if accepted:
        assert safe_load_yaml(source) is not None
    else:
        with pytest.raises(RecursionError):
            safe_load_yaml(source)


@pytest.mark.parametrize("offset", [-2, -1, 0, 5])
def test_both_yaml_readers_agree_about_one_file(offset, tmp_path):
    """`read_yaml` bounds through libyaml, `read_yaml_commented` through
    ruamel, and they must reach the same verdict on the same document.

    ruamel is pure Python, so it raises rather than faulting — but left
    alone it raises wherever the interpreter's stack gives out, which is
    the incidental limit the explicit bound exists to replace. A document
    a hundred levels deep was rejected by one reader and accepted by the
    other, and the two comparisons were off by one against each other.
    """
    from skillsaw.utils import _MAX_YAML_DEPTH, read_yaml, read_yaml_commented

    depth = _MAX_YAML_DEPTH + offset
    target = tmp_path / "nested.yaml"
    target.write_text("extra: " + "[" * depth + "0" + "]" * depth + "\n", encoding="utf-8")

    _, plain_error = read_yaml(target)
    _, commented_error, _ = read_yaml_commented(target)

    assert (plain_error is None) == (commented_error is None)


@pytest.mark.parametrize("leaf", ["0", "{}", "[]"])
def test_the_two_depth_bounds_agree_on_an_empty_terminal_collection(leaf):
    """The two halves measure different things and must still agree.

    ``_reject_deep_before_compose`` counts collection start events;
    ``_reject_overly_nested`` measures the loaded graph's height. An
    empty terminal collection has a start event but holds nothing, so a
    height that begins at zero counts it as one level less than the
    event stream does — and the two halves then disagree at exactly the
    boundary, on whichever install runs only one of them.

    Parametrized over the leaf because a scalar leaf cannot see it: the
    shape that diverged is the empty one.

    Forced onto the pure loader, because that is where the divergence
    lives. With libyaml present ``safe_load_yaml`` runs the prescan too,
    so both sides consult the same bound and agree whatever the height
    measure does — which would make this pass vacuously on CI.
    """
    import skillsaw.utils as utils_module
    from skillsaw.utils import _MAX_YAML_DEPTH, _reject_deep_before_compose, safe_load_yaml

    real_loader = utils_module._SAFE_LOADER
    utils_module._SAFE_LOADER = yaml.SafeLoader
    try:
        _assert_bounds_agree(_MAX_YAML_DEPTH, _reject_deep_before_compose, safe_load_yaml, leaf)
    finally:
        utils_module._SAFE_LOADER = real_loader


def _assert_bounds_agree(_MAX_YAML_DEPTH, _reject_deep_before_compose, safe_load_yaml, leaf):
    for depth in (_MAX_YAML_DEPTH - 3, _MAX_YAML_DEPTH - 2, _MAX_YAML_DEPTH - 1):
        source = (
            "".join("  " * i + f"a{i}:\n" for i in range(depth))
            + "  " * depth
            + f"a{depth}: {leaf}\n"
        )

        try:
            _reject_deep_before_compose(source)
            prescan_rejects = False
        except RecursionError:
            prescan_rejects = True

        try:
            safe_load_yaml(source)
            reader_rejects = False
        except RecursionError:
            reader_rejects = True

        assert prescan_rejects == reader_rejects, (leaf, depth)


def test_aliases_cannot_build_a_graph_deeper_than_the_source_reads(tmp_path):
    """Depth in the text and depth in the object are different numbers.

    The prescan counts what the source spells out. A file of one-line
    entries, each referencing the anchor on the line before it, is two
    levels deep as text and arbitrarily deep as a graph — so the loaded
    object has to be measured too, exactly as `safe_load_yaml` measures
    it after its own prescan. Without that the two readers split on one
    file inside a single run: `coderabbit-yaml-valid` reported a
    `.coderabbit.yaml` too deep to parse while the schema rule, reading
    the same bytes, was handed the graph it had built.
    """
    from skillsaw.utils import _MAX_YAML_DEPTH, _TOO_DEEP, read_yaml, read_yaml_commented

    depth = _MAX_YAML_DEPTH + 50
    lines = ["l0: &a0 [x]"] + [f"l{index}: &a{index} [*a{index - 1}]" for index in range(1, depth)]
    target = tmp_path / "aliased.yaml"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _, plain_error = read_yaml(target)
    data, commented_error, _ = read_yaml_commented(target)

    assert plain_error == _TOO_DEEP
    assert commented_error == _TOO_DEEP
    assert data is None


def test_the_write_paths_load_under_the_same_bound(tmp_path):
    """A writer loads its own document, and must not be the way in.

    ``read_yaml_commented`` is cached, so a caller that edits and writes
    back cannot use it — which is how two block writers came to build a
    bare ``YAML()`` and take untrusted nesting with neither half of the
    bound. Both now go through ``roundtrip_yaml`` and degrade to a no-op
    instead of letting ``RecursionError`` escape into a rule's fix.
    """
    from skillsaw.blocks.coderabbit import CodeRabbitContentBlock
    from skillsaw.blocks.promptfoo import PromptfooPromptBlock
    from skillsaw.utils import _MAX_YAML_DEPTH

    depth = _MAX_YAML_DEPTH + 50
    deep = "[" * depth + "0" + "]" * depth

    config = tmp_path / "promptfooconfig.yaml"
    config.write_text(f"prompts:\n  - hello\nextra: {deep}\n", encoding="utf-8")
    prompt = PromptfooPromptBlock.__new__(PromptfooPromptBlock)
    prompt.path, prompt.yaml_path = config, "prompts[0]"
    prompt.write_body("replaced")
    assert "hello" in config.read_text(encoding="utf-8")

    coderabbit = tmp_path / ".coderabbit.yaml"
    coderabbit.write_text(f"reviews:\n  profile: chill\nextra: {deep}\n", encoding="utf-8")
    review = CodeRabbitContentBlock.__new__(CodeRabbitContentBlock)
    review.path, review.yaml_path = coderabbit, "reviews.profile"
    review.write_body("assertive")
    assert "chill" in coderabbit.read_text(encoding="utf-8")

    # The bound must not cost an ordinary document its edit.
    shallow = tmp_path / "shallow.yaml"
    shallow.write_text("prompts:\n  - old\ndescription: keep me\n", encoding="utf-8")
    writable = PromptfooPromptBlock.__new__(PromptfooPromptBlock)
    writable.path, writable.yaml_path = shallow, "prompts[0]"
    writable.write_body("new")
    written = shallow.read_text(encoding="utf-8")
    assert "new" in written and "keep me" in written


@pytest.mark.parametrize(
    "source, expected",
    [
        # An astral character escaped as a JSON-style surrogate pair, which
        # is what any ASCII-safe JSON-to-YAML conversion emits — an emoji in
        # a skill's `description:`, say. libyaml rejects it outright.
        (r'a: "\uD83D\uDE00"', {"a": "\ud83d\ude00"}),
        # libyaml refuses directives naming a version it does not implement.
        ("%YAML 1.0\n---\na: 1\n", {"a": 1}),
    ],
)
def test_documents_only_the_pure_python_loader_accepts_still_parse(source, expected):
    """The loader swap must not turn a clean file into a parse error.

    These parse on `main`. Left to libyaml alone each becomes an
    ERROR-severity violation on a file that linted cleanly before, which
    is a behaviour regression rather than a speed-up.
    """
    from skillsaw.utils import safe_load_yaml

    assert safe_load_yaml(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "name:\tvalue\n",  # tab separating a key from its value
        "name: value\t\n",  # trailing tab
        "name: value\t# comment\n",  # tab before a comment
        "name\t: value\n",  # tab between a key and its colon
        "name: \tvalue\n",  # space then tab
        "a:\n  b:\tvalue\n",  # nested
        "keywords: [how?, why?]\n",  # ? inside a flow collection
        "globs: [tests/?_*.py]\n",  # the same, as a glob a rule file might carry
        "a: |#\n  x\n",  # block-scalar header followed by a comment marker
    ],
)
@pytest.mark.skipif(
    not hasattr(yaml, "CSafeLoader"),
    reason="the widening is libyaml's; without it safe_load_yaml is the pure loader",
)
def test_documents_only_libyaml_accepts_now_parse(source):
    """The other direction of the accepted-document set, which the
    retry cannot cover.

    A rejected document is retried on the pure-Python loader, so
    anything PyYAML alone accepts still parses. Nothing symmetrical
    happens when libyaml *accepts* — ``yaml.load`` returns and no retry
    runs — so this class changes behaviour on upgrade: a tab used as a
    token separator is a ``ScannerError`` on PyYAML's own scanner and
    parses here. Both YAML 1.1 and 1.2 permit it outside indentation.

    Pinned so the accepted set is characterized in both directions
    rather than asserted in one. These shapes are what has been
    measured, not a proof of the boundary: the class is "documents
    PyYAML's own scanner is stricter than the spec about", and it is
    wider than this list.
    """
    from skillsaw.utils import safe_load_yaml

    with pytest.raises(yaml.YAMLError):
        yaml.load(source, Loader=yaml.SafeLoader)

    assert safe_load_yaml(source) is not None


def test_the_accelerated_loader_is_the_one_under_test():
    """Canary for the tests above, which skip without libyaml.

    Those tests are the only thing characterizing the widened direction,
    and a wheel without the C extension makes them vacuous rather than
    wrong. This one always runs, so a build that quietly lost the
    accelerator says so here instead of going quiet there — and it is
    also the thing that would make every performance claim made for the
    libyaml switch not apply.
    """
    from skillsaw.utils import _SAFE_LOADER

    if hasattr(yaml, "CSafeLoader"):
        assert _SAFE_LOADER is yaml.CSafeLoader
    else:  # pragma: no cover - depends on the installed wheel
        assert _SAFE_LOADER is yaml.SafeLoader


def test_the_line_number_readers_carry_the_depth_bound_too():
    """The bound is a property of every reader, not of the main ones.

    ``_fast_top_level_key_nodes`` composes through libyaml, whose
    composer is recursive C with no guard — handed a deep enough
    document the process dies with SIGSEGV, which no ``except`` can
    catch. ``_ruamel_load`` is pure Python and raises instead, but it
    raises wherever the interpreter's stack gives out, and an escaping
    ``RecursionError`` becomes an unbaselinable rule-execution error
    rather than the parse failure its callers handle.

    Both are reached only after a bounded reader has already accepted
    the file, so neither should see a document like this. That is the
    argument for the guard, not against it: the next reader added here
    will be copied from these.
    """
    from skillsaw.utils import _MAX_YAML_DEPTH, _fast_top_level_key_nodes, _ruamel_load

    deep = "a:\n" + "".join(" " * (i + 1) + "b:\n" for i in range(_MAX_YAML_DEPTH + 50))

    assert _fast_top_level_key_nodes(deep) is None
    assert _ruamel_load(deep) is None

    # A document inside the bound still parses through both.
    shallow = "a:\n  b:\n    c: 1\n"
    assert _fast_top_level_key_nodes(shallow) is not None
    assert _ruamel_load(shallow) is not None


def test_a_tab_used_as_indentation_is_still_an_error():
    """The tab that changed behaviour is the separator, not indentation.

    Indentation by tab is illegal in every YAML version and both
    scanners reject it. Pinned beside the case above so the widening is
    bounded to the shape actually measured.
    """
    from skillsaw.utils import safe_load_yaml

    with pytest.raises(yaml.YAMLError):
        safe_load_yaml("a:\n\tb: value\n")


def test_a_malformed_document_keeps_its_line_number():
    """Callers report the line a parse failed on, so the retry has to
    surface a real error object rather than swallow the mark."""
    from skillsaw.utils import safe_load_yaml

    with pytest.raises(yaml.YAMLError) as caught:
        safe_load_yaml("a: [1, 2\n")

    assert caught.value.problem_mark is not None
    assert caught.value.problem_mark.line == 1


def test_deep_yaml_does_not_abort_the_process():
    """libyaml composes nodes by C-stack recursion with no guard.

    Handed a document nested past roughly fifty thousand levels it
    overruns that stack and the process dies with SIGSEGV, which no
    ``except`` clause can catch — so a check on the constructed object
    cannot be the guard, because it runs after the crash. Driven through
    a subprocess: an in-process fault would take the test worker with it
    rather than being reported.
    """
    import subprocess

    program = (
        "from skillsaw.utils import safe_load_yaml\n"
        "d = 200000\n"
        "try:\n"
        "    safe_load_yaml('extra: ' + '[' * d + '0' + ']' * d)\n"
        "except RecursionError:\n"
        "    print('rejected')\n"
    )
    finished = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=120
    )

    assert finished.returncode == 0, f"crashed with {finished.returncode}"
    assert finished.stdout.strip() == "rejected"


class TestFileCacheBudget:
    """The cache must hold the bound it advertises, and hold the right things."""

    def _cache(self, budget):
        cache = skillsaw_utils.FileCache(budget=budget)
        calls = {"n": 0}

        @cache.cached
        def reader(path, payload=""):
            calls["n"] += 1
            return payload

        return cache, reader, calls

    def test_a_value_larger_than_the_budget_is_not_cached(self, tmp_path):
        """One eviction cannot make room for it, and keeping it would put
        the cache permanently over its bound."""
        cache, reader, calls = self._cache(1000)
        target = tmp_path / "big.txt"

        assert reader(target, "x" * 5000) == "x" * 5000
        assert reader(target, "x" * 5000) == "x" * 5000

        assert calls["n"] == 2, "an oversized value must not be served from the cache"
        assert cache._total_bytes <= 1000

    def test_the_budget_holds_after_a_large_insertion(self, tmp_path):
        """Freeing a fixed half-budget is not enough when the arriving
        entry is itself more than half.

        Sized from what the entries actually cost. A hardcoded budget
        silently stops admitting anything at all once the charge grows —
        the key is charged too, so the cost tracks ``tmp_path`` — and
        then every insert takes the too-large-to-cache exit, nothing is
        stored, and the assertion below passes against an empty cache.
        """
        small = "y" * 100
        small_cost = skillsaw_utils._entry_cost(small, tmp_path / "small0.txt")
        # Sized so the arriving entry is about three quarters of a
        # four-entry budget: comfortably over half, so freeing a fixed
        # half leaves it still not fitting, and under the whole, so it
        # is admissible at all. The payload is derived from the measured
        # cost because the key is charged too — most of a small entry is
        # overhead, not its 100 bytes.
        large = "z" * (2 * small_cost)
        large_cost = skillsaw_utils._entry_cost(large, tmp_path / "large.txt")
        budget = small_cost * 4
        cache, reader, _ = self._cache(budget)

        assert large_cost <= budget, "the large entry must be admissible at all"
        assert large_cost > budget // 2, "or a fixed half-budget would suffice"

        for i in range(4):
            reader(tmp_path / f"small{i}.txt", small)
        assert cache._total_bytes > 0, "the fill must actually cache something"
        assert cache._total_bytes + large_cost > budget, "the insert must evict"

        reader(tmp_path / "large.txt", large)

        assert cache._total_bytes <= budget
        assert cache._total_bytes > 0, "the large entry must have been admitted"

    def test_eviction_does_not_drain_one_store_first(self, tmp_path):
        """Stores are drained in step.

        Emptying the first store first would always sacrifice the
        file-text cache — the largest, and the one the parsed documents
        in the other stores are derived from.
        """
        # Sized from what an entry actually costs rather than a bare
        # number: the charge includes the key, so a fixed budget silently
        # stops holding two entries the moment tmp_path gets longer.
        entry = skillsaw_utils._entry_cost("t" * 100, tmp_path / "f0.txt")
        cache = skillsaw_utils.FileCache(budget=entry * 8)

        @cache.cached
        def text_reader(path):
            return "t" * 100

        @cache.cached
        def parsed_reader(path):
            return "p" * 100

        for i in range(12):
            target = tmp_path / f"f{i}.txt"
            text_reader(target)
            parsed_reader(target)

        text_store, parsed_store = cache._stores
        assert text_store, "the text cache must not be the only one evicted"
        assert parsed_store

    def test_the_resolution_memo_is_bounded_by_bytes_not_entries(self, tmp_path):
        """A ``Path`` is not a fixed-small entry.

        Manifests supply path strings, and at the length a filesystem
        permits a quarter-million of them measured 2.1 GB resident — so a
        count cap cannot express this bound. Past the budget the memo
        simply stops accepting: it is a pure speed optimization over a
        filesystem that has not changed, so declining to remember costs
        time and nothing else.
        """
        from pathlib import Path

        import skillsaw.paths as paths

        paths.clear_resolve_cache()
        budget = paths._RESOLVE_CACHE_BUDGET_BYTES
        try:
            paths._RESOLVE_CACHE_BUDGET_BYTES = 4096
            long_tail = "/".join("d" * 100 for _ in range(8))
            for index in range(200):
                paths.safe_resolve(Path(f"/nonexistent/{index}/{long_tail}"))

            assert paths._resolve_cache_bytes <= 4096
            assert len(paths._RESOLVE_CACHE) < 200, "the budget never stopped admissions"
        finally:
            paths._RESOLVE_CACHE_BUDGET_BYTES = budget
            paths.clear_resolve_cache()

    def test_resolution_paths_are_charged_by_what_they_retain(self):
        """``len()`` is a character count, not a byte count.

        CPython stores one, two or four bytes per character (PEP 393), so
        a manifest naming its directories in emoji retains four times
        what a character count charges. This is the same correction the
        file cache makes for cached text: two paths of equal length and
        unequal storage width retain different numbers of bytes, so
        admission has to charge what is retained rather than how many
        characters were counted.
        """
        from pathlib import Path

        import skillsaw.paths as paths

        # Equal character counts, unequal storage widths.
        narrow = Path("/nonexistent/" + "a" * 500)
        wide = Path("/nonexistent/" + "\U0001f600" * 500)
        assert len(str(narrow)) == len(str(wide))

        try:
            paths.clear_resolve_cache()
            paths.safe_resolve(narrow)
            narrow_charge = paths._resolve_cache_bytes

            paths.clear_resolve_cache()
            paths.safe_resolve(wide)
            wide_charge = paths._resolve_cache_bytes
        finally:
            paths.clear_resolve_cache()

        # Four bytes per character against one, for the key and the
        # resolved value alike. Charging by length makes these equal.
        assert wide_charge > narrow_charge * 2

    def test_a_long_key_costs_more_than_a_short_one(self, tmp_path):
        """The key is variable, so a constant cannot stand in for it.

        ``_ENTRY_OVERHEAD_BYTES`` was tuned against an ordinary repository
        path, where it is almost exactly right. Manifests supply the
        strings, though, and a 4 KB path retains twelve times it. A
        ``Path`` key is variable-sized, so the file cache measures it the
        same way the resolution memo does rather than folding it into a
        constant.
        """
        short = tmp_path / "a.md"
        long = tmp_path / ("/".join("d" * 60 for _ in range(60)) + "/a.md")

        value = "x" * 100
        short_cost = skillsaw_utils._entry_cost(value, short)
        long_cost = skillsaw_utils._entry_cost(value, long)

        # Same value, same machinery; only the key differs.
        assert long_cost > short_cost + 3000, (short_cost, long_cost)
        # And a keyless call still charges value plus machinery.
        assert skillsaw_utils._entry_cost(value) < short_cost

    def test_an_aliased_scalar_is_charged_once_not_once_per_use(self):
        """An anchor is one object however many times a document names it.

        Counting references is counting memory that is not there: a 2 MiB
        anchored string used 64 times charged 128.0 MiB against the 2.0
        MiB it holds — over the default budget, so the entry is refused
        and every rule reparses the file the accounting was meant to keep
        cached.
        """
        shared = "x" * (2 * 1024 * 1024)
        document = {"anchor": shared, "uses": [shared] * 63}

        charged = skillsaw_utils._approximate_size(document)

        assert charged < 3 * 1024 * 1024, charged
        assert charged <= skillsaw_utils.FileCache.DEFAULT_BUDGET

        # Distinct scalars of the same size must still be charged apiece,
        # or the dedup has traded one wrong number for another.
        distinct = {"a": "y" * 5000, "b": "z" * 5000}
        assert skillsaw_utils._approximate_size(distinct) > 10_000

    def test_resolution_is_dropped_before_the_reads_keyed_on_it(self, tmp_path):
        """Two caches, one invalidation, and the order is the safety.

        A reader captures the cache generation before it resolves. Clear
        the file cache first and there is a window where a reader
        captures the *new* generation and still resolves an old target
        from the memo, then files the new target's bytes under it.
        """
        import inspect

        import skillsaw.paths as paths

        source = inspect.getsource(skillsaw_utils.invalidate_read_caches)
        drops_identity = source.index("invalidate_path_identity()")
        clears_files = source.index("_file_cache.invalidate(")
        assert drops_identity < clears_files, "resolution must be dropped first"

        # And the helper it delegates to keeps the same order internally.
        helper = inspect.getsource(skillsaw_utils.invalidate_path_identity)
        assert helper.index("clear_resolve_cache()") < helper.index("_generation += 1")

        # And both actually happen.
        target = tmp_path / "a.md"
        target.write_text("hello", encoding="utf-8")
        skillsaw_utils.read_text(target)
        paths.safe_resolve(target)
        assert paths._resolve_cache_bytes > 0

        skillsaw_utils.invalidate_read_caches()

        assert paths._resolve_cache_bytes == 0
        assert skillsaw_utils._file_cache._total_bytes == 0

    def test_a_slots_string_is_one_slot_not_many_characters(self):
        """``__slots__ = "_yaml_anchor"`` is legal and means one slot.

        Iterating the string yields its characters, so the attribute walk
        looked up attributes named ``_``, ``y``, ``a`` … found none, and
        did nothing at all — for every ruamel ``ScalarString``, which is
        exactly where the metadata it was added to reach lives.
        """
        from ruamel.yaml.scalarstring import ScalarString

        assert skillsaw_utils._slot_names(ScalarString) == ("_yaml_anchor",)

        declared_as_string = type("OneSlot", (), {"__slots__": "solo"})
        assert skillsaw_utils._slot_names(declared_as_string) == ("solo",)

    def test_an_anchor_name_is_charged_with_its_scalar(self):
        """A string subclass can carry metadata; a plain ``str`` cannot.

        ruamel hands back ``ScalarString`` objects holding an ``Anchor``,
        and an anchor name is authored text of any length. Returning as
        soon as the object is recognised as ``str`` charges the scalar's
        own text and leaves that name uncounted, so the scalar branch has
        to walk the object's attributes like every other branch does.
        """
        from skillsaw.utils import _RuamelYAML

        name = "A" * 2_000_000
        document = _RuamelYAML().load(f"key: &{name} value\nother: *{name}\n")

        charged = skillsaw_utils._approximate_size(document)

        assert charged >= sys.getsizeof(name), charged
        # An ordinary document must not pay for the machinery.
        plain = _RuamelYAML().load("a: 1\nb: [x, y]\nc: hello\n")
        assert skillsaw_utils._approximate_size(plain) < 20_000

    def test_a_long_component_is_charged_by_what_the_path_keeps(self):
        """A ``Path`` keeps its own string alive more than once.

        The rendered path lives in ``_str`` and the components separately
        — ``_parts`` before 3.12, ``_raw_paths`` plus a normcase cache
        after — so a one-million-character component retains two to three
        times what one copy measures. The per-component term covers a
        path's structure; nothing covered its length.
        """
        from pathlib import Path

        import skillsaw.paths as paths

        component = "z" * 200_000
        long_path = Path("/tmp/" + component)

        charged = paths._path_cost(long_path)

        assert charged >= 2 * sys.getsizeof(str(long_path)), charged

    def test_declaring_paths_moved_refuses_a_read_that_predates_it(self, tmp_path):
        """Clearing the memo alone tells the cache keyed by it nothing.

        ``RepositoryContext`` and ``rebuild_lint_tree`` both declare that
        path identity may have changed. A reader already in flight has
        resolved under the old identity, and without a generation bump it
        finishes and files the new target's bytes under the old target's
        key — a read of that path then returns the wrong file.

        The cache is *not* emptied: a retargeted link does not change what
        the file it used to point at contains.
        """
        from pathlib import Path

        old = tmp_path / "old.md"
        new = tmp_path / "new.md"
        old.write_text("OLD", encoding="utf-8")
        new.write_text("NEW", encoding="utf-8")
        link = tmp_path / "link.md"
        link.symlink_to(old)

        skillsaw_utils.invalidate_read_caches()
        # A second file's entry must survive; only the racing read is refused.
        bystander = tmp_path / "bystander.md"
        bystander.write_text("KEEP", encoding="utf-8")
        skillsaw_utils.read_text(bystander)

        real_resolve = skillsaw_utils.safe_resolve
        armed = [True]

        def resolve_then_declare_moved(path):
            resolved = real_resolve(path)
            if armed[0] and path == link:
                armed[0] = False
                link.unlink()
                link.symlink_to(new)
                skillsaw_utils.invalidate_path_identity()
            return resolved

        skillsaw_utils.safe_resolve = resolve_then_declare_moved
        try:
            assert skillsaw_utils.read_text(link) == "NEW"
        finally:
            skillsaw_utils.safe_resolve = real_resolve

        assert skillsaw_utils.read_text._store.get(old.resolve()) is None
        assert skillsaw_utils.read_text._store.get(bystander.resolve()) is not None
        skillsaw_utils.invalidate_read_caches()

    def test_the_refusal_marker_evicts_like_any_other_entry(self, tmp_path):
        """The marker is small, but it is not free.

        It is charged, so a cache already at its budget has to make room
        for it like anything else. If it were stored without going
        through eviction the total would creep past the bound one
        unsizeable file at a time -- and the marker exists precisely for
        repositories with many of them.
        """
        cache = skillsaw_utils.FileCache(budget=4096)

        @cache.cached
        def small(path):
            return "x" * 200

        @cache.cached
        def unsizeable(path):
            return list(range(skillsaw_utils._SIZE_WALK_LIMIT + 10))

        # Fill the cache to the point where an insert must evict.
        for i in range(40):
            small(tmp_path / f"small{i}.md")
        assert cache._total_bytes <= cache._budget
        filled = cache._total_bytes
        assert filled > 0, "the fixture must actually fill the cache"

        target = tmp_path / "huge.json"
        assert len(unsizeable(target)) == skillsaw_utils._SIZE_WALK_LIMIT + 10

        assert cache._total_bytes <= cache._budget, "the marker must not push it over"

        stored = [
            value
            for store in cache._stores
            for bucket in store.values()
            for _cost, value in bucket.values()
        ]
        assert skillsaw_utils._UNSIZEABLE in stored, "the refusal was still recorded"

        # And the recorded refusal still does its job after the eviction.
        assert len(unsizeable(target)) == skillsaw_utils._SIZE_WALK_LIMIT + 10

    def test_a_read_spanning_either_half_of_an_identity_change_is_refused(self, tmp_path):
        """``invalidate_path_identity`` is two statements, not one.

        It drops the resolution memo and then bumps the file cache's
        generation. A reader that resolves before the first and admits
        between them passes a check against the counter that has not
        moved yet — and files the *new* target's bytes under the *old*
        target's resolved key, where a later direct read finds them.

        Reproduced deterministically by releasing the reader inside that
        window rather than by racing threads.
        """
        import skillsaw.paths as paths

        old_target = tmp_path / "old.txt"
        new_target = tmp_path / "new.txt"
        old_target.write_text("OLD", encoding="utf-8")
        new_target.write_text("NEW", encoding="utf-8")
        link = tmp_path / "link.txt"
        link.symlink_to(old_target)

        real_resolve = skillsaw_utils.safe_resolve

        def resolve_then_retarget(path):
            resolved = real_resolve(path)
            if path == link:
                # The window: the link moves and the memo is dropped, but
                # the file cache has not been told yet.
                link.unlink()
                link.symlink_to(new_target)
                paths.clear_resolve_cache()
            return resolved

        skillsaw_utils.safe_resolve = resolve_then_retarget
        try:
            assert skillsaw_utils.read_text(link) == "NEW"
            # Asserted before any teardown: clearing the cache first would
            # make an empty store prove nothing.
            stale = skillsaw_utils.read_text._store.get(old_target.resolve())
        finally:
            skillsaw_utils.safe_resolve = real_resolve
            skillsaw_utils.invalidate_read_caches()

        # Whatever the reader was handed, nothing may be filed under the
        # resolution that was declared stale mid-read.
        assert stale is None, stale

    def test_the_lost_race_never_hands_back_the_refusal_marker(self, tmp_path):
        """The store's other value-returning exit needs the same guard.

        A reader computes outside the lock. If another caller fills the
        key in that window, this one keeps what is already charged
        rather than overwriting it — but what is already charged may be
        the refusal marker, and the caller asked for a document. No
        threads are needed to reach it: the branch fires whenever the
        key appears between the miss and the insert, so the reader
        plants it itself.
        """
        target = tmp_path / "raced.json"
        cache = skillsaw_utils.FileCache(budget=1 << 20)
        planted = {"done": False}

        @cache.cached
        def reader(path):
            if not planted["done"]:
                planted["done"] = True
                # Land the key while this call is outside the lock —
                # exactly what a second thread would have done.
                resolved = skillsaw_utils.safe_resolve(path) or path
                marker = skillsaw_utils._entry_cost(skillsaw_utils._UNSIZEABLE, resolved)
                store = reader._store
                store.setdefault(resolved, {})[((), ())] = (
                    marker,
                    skillsaw_utils._UNSIZEABLE,
                )
                cache._total_bytes += marker
            return {"real": "document"}

        result = reader(target)

        assert planted["done"], "the race window must actually have been used"
        assert result == {"real": "document"}
        assert result is not skillsaw_utils._UNSIZEABLE
        assert not isinstance(result, skillsaw_utils._Unsizeable)

    def test_the_superseded_maxsize_keyword_still_constructs_a_cache(self):
        """``skillsaw.utils`` is re-exported wholesale to custom rules.

        ``skillsaw.rules.builtin.utils`` does ``from skillsaw.utils import
        *`` and promises in its own docstring that a custom rule importing
        from it keeps working unchanged. There is no ``__all__`` holding
        anything back, so ``FileCache`` is reachable and its constructor
        is part of that promise. Renaming the argument turned a working
        call into a ``TypeError``.

        The count cannot be honoured — the byte budget exists because
        entries are not the same size — so the value is ignored and the
        caller is told once.
        """
        import warnings as warnings_module

        with warnings_module.catch_warnings(record=True) as caught:
            warnings_module.simplefilter("always")
            cache = skillsaw_utils.FileCache(maxsize=2048)

        assert cache._budget == skillsaw_utils.FileCache.DEFAULT_BUDGET
        assert len(caught) == 1, caught
        assert issubclass(caught[0].category, DeprecationWarning)
        assert "budget=" in str(caught[0].message)

        # The same call through the shim a custom rule actually imports.
        from skillsaw.rules.builtin.utils import FileCache as ShimFileCache

        assert ShimFileCache is skillsaw_utils.FileCache

    def test_a_marker_too_large_for_the_budget_is_not_stored(self, tmp_path):
        """The refusal marker obeys the bound it is helping to keep.

        It is small, but a budget can be smaller. Eviction cannot make
        room for an entry larger than the whole budget, so admitting one
        would leave the cache permanently over the bound — the same rule
        the value path follows. The refusal is simply not remembered
        there, which costs the walk again and breaks nothing.
        """
        target = tmp_path / "huge.json"
        resolved = skillsaw_utils.safe_resolve(target) or target
        marker = skillsaw_utils._entry_cost(skillsaw_utils._UNSIZEABLE, resolved)
        cache = skillsaw_utils.FileCache(budget=marker - 1)

        @cache.cached
        def unsizeable(path):
            return list(range(skillsaw_utils._SIZE_WALK_LIMIT + 10))

        assert len(unsizeable(target)) == skillsaw_utils._SIZE_WALK_LIMIT + 10
        assert cache._total_bytes == 0, "nothing may be stored over the bound"
        assert cache._total_bytes <= cache._budget

        # Still returns the right answer, just without remembering.
        assert len(unsizeable(target)) == skillsaw_utils._SIZE_WALK_LIMIT + 10

    @pytest.mark.parametrize("anchored", ["{k: v}", "[v]", "hello", ""])
    def test_an_aliased_graph_is_sized_by_its_objects_not_its_references(self, anchored):
        """The walk limit bounds distinct objects, not names for them.

        An alias is ordinary in YAML and a document may name one anchor
        tens of thousands of times. Charging the limit per reference
        abandons the walk over a graph holding three objects, and an
        abandoned walk is not free: the value cannot be cached, so every
        rule reparses the file — far more expensive than finishing.

        Every node kind, not just containers. Registering only large
        scalars leaves 20,000 references to one short string — or to one
        null — exhausting the limit just the same, and a container-only
        case cannot see that: containers are registered either way.
        """
        count = skillsaw_utils._SIZE_WALK_LIMIT + 5_000
        source = f"anchor: &x {anchored}\nitems:\n" + "".join("  - *x\n" for _ in range(count))
        data = skillsaw_utils.safe_load_yaml(source)

        assert len({id(item) for item in data["items"]}) == 1, "one object, many names"

        size = skillsaw_utils._approximate_size(data)
        assert size != skillsaw_utils.UNCACHEABLE_SIZE
        assert size > 0

    def test_the_walk_limit_still_rejects_a_genuinely_large_graph(self):
        """Counting distinct objects must not disarm the bound.

        The limit exists so cache accounting cannot run unbounded on a
        hostile document. Deduplicating references must not turn it off
        for a graph that really does hold that many objects.
        """
        huge = list(range(skillsaw_utils._SIZE_WALK_LIMIT + 10_000))
        assert skillsaw_utils._approximate_size(huge) == skillsaw_utils.UNCACHEABLE_SIZE

    def test_a_cycle_terminates_the_walk(self):
        """Aliases and cycles are both ordinary in YAML.

        A cycle is terminated by the identity check, not by the walk
        limit: a repeated reference is skipped before it is counted, so
        the limit is never reached. Pin that it does terminate.
        """
        looping_list = []
        looping_list.append(looping_list)
        assert skillsaw_utils._approximate_size(looping_list) > 0

        looping_map = {}
        looping_map["self"] = looping_map
        assert skillsaw_utils._approximate_size(looping_map) > 0

    def test_a_value_too_large_to_size_is_walked_once_not_every_call(self, tmp_path):
        """Refusing to cache must not mean re-deciding on every call.

        Past ``_SIZE_WALK_LIMIT`` the value cannot be admitted — the
        budget would record a number that is not what the entry holds.
        Forgetting *that* costs the whole abandoned walk again on every
        later call, on top of the recompute, which is worse than doing
        no accounting at all. The verdict is remembered; the value still
        is not.
        """
        cache = skillsaw_utils.FileCache(budget=100_000_000)
        walks = []
        real_size = skillsaw_utils._approximate_size

        def counting_size(value):
            walks.append(1)
            return real_size(value)

        oversize = list(range(skillsaw_utils._SIZE_WALK_LIMIT + 10))

        @cache.cached
        def reader(path):
            return list(oversize)

        target = tmp_path / "big.json"
        target.write_text("{}", encoding="utf-8")

        skillsaw_utils._approximate_size = counting_size
        try:
            first = reader(target)
            walked_once = len(walks)
            for _ in range(3):
                assert reader(target) == first
            walked_after = len(walks)
        finally:
            skillsaw_utils._approximate_size = real_size

        # The value is still correct and still not cached...
        assert first == oversize
        # ...but the walk is not repeated. Without the marker this grows
        # by one full abandoned walk per call.
        assert walked_after == walked_once, (walked_once, walked_after)

    def test_a_clear_during_a_resolution_is_not_undone_by_it(self, tmp_path):
        """The sibling of the ``FileCache`` generation check.

        ``Path.resolve()`` runs outside the lock, so a clear can land
        between the syscall and the insert. Without a generation the
        pre-change target is written in after the drop meant to remove
        it, and every later containment check and cached read is handed a
        target the filesystem no longer has.
        """
        from pathlib import Path

        import skillsaw.paths as paths

        old = tmp_path / "old"
        new = tmp_path / "new"
        old.mkdir()
        new.mkdir()
        link = tmp_path / "link"
        link.symlink_to(old)

        paths.clear_resolve_cache()
        real_resolve = Path.resolve
        armed = [True]

        def resolve_then_clear(self, *args, **kwargs):
            resolved = real_resolve(self, *args, **kwargs)
            if armed[0] and self == link:
                armed[0] = False
                link.unlink()
                link.symlink_to(new)
                paths.clear_resolve_cache()
            return resolved

        Path.resolve = resolve_then_clear
        try:
            # The caller still gets the answer it asked for...
            assert paths.safe_resolve(link) == old.resolve()
        finally:
            Path.resolve = real_resolve

        # ...but it must not outlive the clear that overtook it.
        assert link not in paths._RESOLVE_CACHE
        assert paths._resolve_cache_bytes == 0
        assert paths.safe_resolve(link) == new.resolve()
        paths.clear_resolve_cache()

    def test_clearing_the_resolution_memo_resets_its_accounting(self):
        """Otherwise the budget is spent once and never recovered, and the
        memo stops working for every later pass in a long-lived process."""
        from pathlib import Path

        import skillsaw.paths as paths

        paths.safe_resolve(Path("/nonexistent/probe"))
        assert paths._resolve_cache_bytes > 0

        paths.clear_resolve_cache()

        assert paths._resolve_cache_bytes == 0
        assert not paths._RESOLVE_CACHE

    def test_a_value_too_large_to_size_is_never_cached(self, tmp_path):
        """The size walk gives up past ``_SIZE_WALK_LIMIT`` nodes.

        What it returns then has to be rejected by every budget, not just
        the default one: a concrete number is admitted by any cache
        configured above it, and then charged at whatever the walk had
        counted so far, which is exactly the accounting the byte budget
        exists to keep honest. The refusal itself is remembered, so the
        budget carries a marker entry -- bounded, and unrelated to how
        large the value it stands in for was.
        """
        huge = list(range(skillsaw_utils._SIZE_WALK_LIMIT + 10))
        assert skillsaw_utils._approximate_size(huge) == skillsaw_utils.UNCACHEABLE_SIZE

        # A budget far above anything the walk could have counted.
        cache = skillsaw_utils.FileCache(budget=1 << 40)
        calls = {"n": 0}

        @cache.cached
        def reader(path):
            calls["n"] += 1
            return list(range(skillsaw_utils._SIZE_WALK_LIMIT + 10))

        target = tmp_path / "huge.yaml"
        assert reader(target) == huge
        assert reader(target) == huge

        assert calls["n"] == 2, "an unsized value must be recomputed, not served"

        resolved = skillsaw_utils.safe_resolve(target) or target
        marker = skillsaw_utils._entry_cost(skillsaw_utils._UNSIZEABLE, resolved)
        assert cache._total_bytes == marker, "only the refusal is charged"
        assert cache._total_bytes < sys.getsizeof(huge), "never the value itself"

    def test_an_object_that_refuses_to_be_sized_is_charged_the_flat_estimate(self):
        """``sys.getsizeof`` runs attacker-influenced ``__sizeof__`` code.

        A parsed document can carry an object whose ``__sizeof__`` raises
        or returns a non-integer. Letting that escape would abort a lint
        from inside cache accounting -- a read of the file is what asked
        for the size, and the caller only wanted the file's contents.
        """

        class Hostile:
            def __sizeof__(self):
                raise TypeError("no size for you")

        class Liar:
            def __sizeof__(self):
                return "not an integer"

        for value in (Hostile(), Liar()):
            size = skillsaw_utils._approximate_size(value)
            assert size >= skillsaw_utils._NODE_OVERHEAD_BYTES, value
            assert isinstance(size, int)

        # And the same object nested inside a document still sizes.
        nested = {"a": [Hostile(), {"b": Liar()}]}
        assert skillsaw_utils._approximate_size(nested) > 0

    def test_a_scalar_is_charged_by_what_it_retains(self):
        """A scalar is not always small.

        PyYAML resolves ``0x`` followed by a few million hex digits into a
        multi-megabyte ``int`` — and unlike the decimal path, the hex one
        has no digit limit to stop it. Charged a flat estimate, an
        arbitrary number of such documents sit in the cache while the
        total stays near zero.
        """
        big = int("f" * 200_000, 16)

        charged = skillsaw_utils._approximate_size(big)

        assert charged >= sys.getsizeof(big)
        assert skillsaw_utils._approximate_size(None) == skillsaw_utils._NODE_OVERHEAD_BYTES

    def test_mutating_a_cached_value_does_not_corrupt_the_total(self, tmp_path):
        """The readers hand back parsed documents a caller can mutate.

        Recomputing an entry's size at teardown charges back whatever it
        measures then, not what admission charged: growing a cached
        mapping drove the total negative, shrinking one left phantom
        bytes behind.
        """
        cache = skillsaw_utils.FileCache(budget=1_000_000)

        @cache.cached
        def reader(path):
            return {"k": "v"}

        grown = reader(tmp_path / "a.yaml")
        grown["big"] = "x" * 100_000
        reader.cache_clear()
        assert cache._total_bytes == 0

        shrunk = reader(tmp_path / "b.yaml")
        shrunk.clear()
        cache.invalidate(tmp_path / "b.yaml")
        assert cache._total_bytes == 0

    def test_an_invalidation_during_a_read_is_not_undone_by_it(self, tmp_path):
        """A reader computes outside the lock, so a drop can land mid-read.

        Autofix invalidates after writing. If the pre-change value is
        inserted after the drop meant to remove it, the cache serves
        content from before the write for the rest of the pass — the one
        thing invalidation exists to prevent.
        """
        import threading

        cache = skillsaw_utils.FileCache(budget=1_000_000)
        reading = threading.Event()
        values = iter(["before the write", "after the write"])

        @cache.cached
        def reader(path):
            value = next(values)
            if value == "before the write":
                reading.set()
                threading.Event().wait(0.2)
            return value

        target = tmp_path / "rewritten.md"
        in_flight = threading.Thread(target=lambda: reader(target))
        in_flight.start()
        assert reading.wait(5)
        cache.invalidate(target)
        in_flight.join(10)

        assert reader(target) == "after the write"

    def test_the_key_and_the_generation_describe_one_filesystem(self, tmp_path):
        """Resolving the key is itself an answer about the filesystem.

        A generation captured after the resolve cannot tell that an
        invalidation landed in between, so a symlink retargeted in that
        window has the new target's bytes filed under the old target's
        key — and a later direct read of the old path is served the wrong
        file for the rest of the pass. Capturing at entry covers the
        resolve as well as the read.
        """
        import skillsaw.paths as paths

        old = tmp_path / "old.txt"
        new = tmp_path / "new.txt"
        old.write_text("OLD", encoding="utf-8")
        new.write_text("NEW", encoding="utf-8")
        link = tmp_path / "link.txt"
        link.symlink_to(old)

        cache = skillsaw_utils.FileCache(budget=1_000_000)

        @cache.cached
        def reader(path):
            return path.read_text(encoding="utf-8")

        real_resolve = skillsaw_utils.safe_resolve
        armed = [True]

        def resolve_then_move(path):
            resolved = real_resolve(path)
            if armed[0]:
                # Exactly the window under test: after the key is
                # resolved, before the read that fills it.
                armed[0] = False
                link.unlink()
                link.symlink_to(new)
                paths.clear_resolve_cache()
                cache.invalidate()
            return resolved

        skillsaw_utils.safe_resolve = resolve_then_move
        try:
            assert reader(link) == "NEW"
        finally:
            skillsaw_utils.safe_resolve = real_resolve
            paths.clear_resolve_cache()

        # The read describes the post-move filesystem; the key describes
        # the pre-move one. Nothing that mismatched may be retained.
        assert reader._store.get(old.resolve()) is None
        assert cache._total_bytes == 0

    def test_racing_readers_agree_on_one_value_and_one_charge(self, tmp_path):
        """Two threads missing the same key both compute outside the lock.

        Whoever loses must not overwrite the winner's value, or the cache
        holds one value while the budget records the cost of another and
        invalidation subtracts a charge that was never added.
        """
        import threading

        cache = skillsaw_utils.FileCache(budget=10_000_000)
        started = threading.Barrier(4)
        sizes = iter([100, 200_000, 300_000, 400_000])
        lock = threading.Lock()

        @cache.cached
        def reader(path):
            with lock:
                size = next(sizes)
            started.wait(timeout=5)
            return "x" * size

        target = tmp_path / "contended.md"
        seen = []
        threads = [threading.Thread(target=lambda: seen.append(reader(target))) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(set(seen)) == 1, "every caller must be handed the same value"
        cache.invalidate(target)
        assert cache._total_bytes == 0

    def test_comment_metadata_is_charged_not_walked_past(self, tmp_path):
        """ruamel keeps comments beside a mapping, not inside it.

        Comment tokens hang off ``.ca``, which a walk descending only keys
        and values never reaches — a comment-heavy config retained about
        three times what it was charged. A ``CommentedMap`` is itself a
        ``dict``, so the container branches have to ask for attributes
        too; asking only in the scalar tail walks past every one.
        """
        from skillsaw.utils import read_yaml_commented

        body = "\n".join(f"k{i}: v" for i in range(200)) + "\n"
        commented = "\n".join(f"# {'c' * 200}\nk{i}: v" for i in range(200)) + "\n"
        (tmp_path / "plain.yaml").write_text(body, encoding="utf-8")
        (tmp_path / "commented.yaml").write_text(commented, encoding="utf-8")

        plain = skillsaw_utils._approximate_size(read_yaml_commented(tmp_path / "plain.yaml"))
        rich = skillsaw_utils._approximate_size(read_yaml_commented(tmp_path / "commented.yaml"))

        # Same data either way; the difference is comment tokens alone.
        assert rich == skillsaw_utils.UNCACHEABLE_SIZE or rich > plain * 2

    def test_text_is_charged_by_what_it_retains_not_its_length(self):
        """CPython stores a string at one, two or four bytes per character
        (PEP 393), so a document of emoji retains four times the length a
        ``len``-based estimate would have shown the budget."""
        astral = "\U0001f600" * 100_000

        charged = skillsaw_utils._approximate_size(astral)

        assert charged >= sys.getsizeof(astral) - skillsaw_utils._NODE_OVERHEAD_BYTES
        assert charged > 2 * len(astral), "a 4-byte-per-char string charged as 1 byte per char"

    def test_an_entry_is_charged_for_the_machinery_holding_it(self, tmp_path):
        """A cache entry is not only its value.

        It also retains the resolved ``Path`` key, the per-path bucket, the
        sub-key tuple and a slot in each dict. Charged by value alone, an
        empty read costs one byte against several hundred really held, and
        a repository of many small files is bounded by nothing.
        """
        cache, reader, _ = self._cache(1_000_000)
        for i in range(500):
            reader(tmp_path / f"empty{i}.md", "")

        assert cache._total_bytes >= 500 * skillsaw_utils._ENTRY_OVERHEAD_BYTES

    def test_invalidating_credits_back_exactly_what_admission_charged(self, tmp_path):
        """Otherwise the total drifts up on every write-invalidate cycle
        until the cache evicts everything on every insertion."""
        cache, reader, _ = self._cache(1_000_000)
        target = tmp_path / "a.md"

        for _ in range(20):
            reader(target, "some body text")
            cache.invalidate(target)

        assert cache._total_bytes == 0


def test_frontmatter_rejects_a_document_nested_past_the_limit():
    """The depth guard raises RecursionError; readers report it, not crash."""
    from skillsaw.rules.builtin.rules_dir.valid import _parse_frontmatter
    from skillsaw.utils import _MAX_YAML_DEPTH

    depth = _MAX_YAML_DEPTH + 5
    content = "---\nextra: " + "[" * depth + "0" + "]" * depth + "\n---\nbody\n"

    data, error = _parse_frontmatter(content)

    assert data is None
    assert error is not None and "too deep" in error


def test_writing_frontmatter_nested_past_the_limit_raises_value_error(tmp_path):
    from skillsaw.blocks import SkillBlock
    from skillsaw.utils import _MAX_YAML_DEPTH

    target = tmp_path / "SKILL.md"
    target.write_text("---\nname: x\n---\nbody\n", encoding="utf-8")
    block = SkillBlock(path=target)
    depth = _MAX_YAML_DEPTH + 5

    with pytest.raises(ValueError, match="Invalid YAML"):
        block.write_frontmatter_text("extra: " + "[" * depth + "0" + "]" * depth)


def test_depth_guard_measures_the_real_graph_depth():
    """A shared anchor counts at its deepest use, not its first.

    Marking a container visited and skipping it would measure only where
    it was reached first, so a document that mentions a deep anchor
    shallowly before nesting it deeply would be accepted at a fraction of
    its real depth.
    """
    from skillsaw.utils import _MAX_YAML_DEPTH, safe_load_yaml

    half = _MAX_YAML_DEPTH // 2
    anchor = "anchor: &x " + "[" * half + "0" + "]" * half + "\n"
    deep = "deep: " + "[" * _MAX_YAML_DEPTH + "*x" + "]" * _MAX_YAML_DEPTH + "\n"
    shallow = "shallow: [*x]\n"

    for ordering in (anchor + shallow + deep, anchor + deep + shallow):
        with pytest.raises(RecursionError):
            safe_load_yaml(ordering)


def test_approximate_size_charges_a_parsed_document_its_structure():
    """A whole document charged as though it were a scalar is one the
    byte budget cannot see.

    Built by parsing rather than from literals. ``"v" * 100`` written
    inside a comprehension is constant-folded, so every iteration shares
    one string object — and the walk charges an object once however many
    names reach it, which would make this measure interning rather than
    structure. A real document's values are distinct objects.
    """
    import json

    from skillsaw.utils import _approximate_size

    small = _approximate_size((json.loads('{"name": "x"}'), None))
    large = _approximate_size(
        (
            json.loads(json.dumps({"items": [{"k": f"{i:03d}" + "v" * 100} for i in range(200)]})),
            None,
        )
    )

    assert large > 100 * small


def test_safe_load_yaml_accepts_anchor_cycles():
    """An alias cycle is a valid document, not unbounded nesting."""
    from skillsaw.utils import safe_load_yaml

    data = safe_load_yaml("metadata: &m\n  nested: *m\n")

    assert data["metadata"]["nested"] is data["metadata"]


def test_parse_frontmatter_invalid_timestamp_is_a_parse_error():
    content = "---\ndate: 2026-02-30\n---\nBody\n"

    fm, body, error_line = parse_frontmatter(content)

    assert fm is None
    assert body == content
    assert error_line is None


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


class TestStripJsonc:
    """JSONC tolerance: comments and trailing commas, with offsets preserved."""

    def test_line_and_block_comments_become_spaces(self):
        import json

        from skillsaw.utils import strip_jsonc

        source = '{\n  // a note\n  "a": 1, /* inline */ "b": 2\n}'
        stripped = strip_jsonc(source)
        assert json.loads(stripped) == {"a": 1, "b": 2}
        assert len(stripped) == len(source)
        assert stripped.count("\n") == source.count("\n")

    def test_trailing_commas_are_removed_in_objects_and_arrays(self):
        import json

        from skillsaw.utils import strip_jsonc

        source = '{"a": [1, 2,], "b": {"c": 3,},}'
        assert json.loads(strip_jsonc(source)) == {"a": [1, 2], "b": {"c": 3}}

    def test_separating_commas_survive(self):
        import json

        from skillsaw.utils import strip_jsonc

        source = '{"a": [1, [2], 3], "b": 4}'
        assert json.loads(strip_jsonc(source)) == {"a": [1, [2], 3], "b": 4}

    def test_comment_and_comma_syntax_inside_strings_is_data(self):
        import json

        from skillsaw.utils import strip_jsonc

        source = '{"url": "https://x.example//p", "csv": "a,", "b": "/* not */"}'
        assert json.loads(strip_jsonc(source)) == {
            "url": "https://x.example//p",
            "csv": "a,",
            "b": "/* not */",
        }

    def test_an_escaped_quote_does_not_end_the_string(self):
        import json

        from skillsaw.utils import strip_jsonc

        source = '{"a": "he said \\" // not a comment"}'
        assert json.loads(strip_jsonc(source)) == {"a": 'he said " // not a comment'}

    def test_an_unterminated_block_comment_runs_to_end_of_file(self):
        import json

        from skillsaw.utils import strip_jsonc

        source = '{"a": 1}\n/* trailing'
        assert json.loads(strip_jsonc(source)) == {"a": 1}

    def test_parse_error_positions_still_point_at_the_real_line(self, tmp_path):
        """Blanking rather than deleting is what keeps the reported line honest."""
        from skillsaw.utils import read_jsonc

        path = tmp_path / "opencode.jsonc"
        path.write_text('{\n  // a note\n  "a": 1\n  "b": 2\n}\n')
        data, error = read_jsonc(path)
        assert data is None
        assert "line 4" in error

    def test_a_newline_inside_a_block_comment_is_kept(self, tmp_path):
        """The one branch that would shift every line below a `/* */` comment."""
        from skillsaw.utils import read_jsonc

        path = tmp_path / "opencode.jsonc"
        path.write_text('{\n  /* two\n     lines */\n  "a": 1\n  "b": 2\n}\n')
        data, error = read_jsonc(path)
        assert data is None
        assert "line 5" in error

    def test_a_plain_json_document_never_reaches_the_stripper(self, tmp_path, monkeypatch):
        """Valid JSON parses as-is, so the per-character scan is off the common path."""
        import skillsaw.utils as utils_module
        from skillsaw.utils import read_jsonc

        def _fail(content):
            raise AssertionError("strip_jsonc must not run on a document that parses")

        monkeypatch.setattr(utils_module, "strip_jsonc", _fail)
        path = tmp_path / "opencode.json"
        path.write_text('{"a": [1, 2], "b": {"c": "https://x.example//p"}}')
        assert read_jsonc(path) == ({"a": [1, 2], "b": {"c": "https://x.example//p"}}, None)

    def test_read_jsonc_rejects_the_non_finite_extension(self, tmp_path):
        from skillsaw.utils import read_jsonc

        path = tmp_path / "opencode.jsonc"
        path.write_text('{"timeout": NaN}')
        data, error = read_jsonc(path)
        assert data is None
        assert "NaN" in error


class TestOpenCodeTimeout:
    """`timeout` is a number in 1.x and an object in 2.0, and upstream ships
    two disagreeing declarations of that object — so the accepted key set is
    their union."""

    @pytest.mark.parametrize(
        "value",
        [
            5000,
            0,
            30.5,
            {},
            {"startup": 45000, "catalog": 30000, "execution": 600000},
            {"startup": 5000, "request": 10000},
            {"catalog": 1},
        ],
    )
    def test_accepted(self, value):
        from skillsaw.formats.opencode import timeout_is_valid

        assert timeout_is_valid(value)

    @pytest.mark.parametrize(
        "value",
        [
            True,
            False,
            "30s",
            None,
            [30000],
            {"startup": True},
            {"catalog": "30s"},
            {"unknown": 1},
            {"startup": 1, "unknown": 2},
        ],
    )
    def test_rejected(self, value):
        from skillsaw.formats.opencode import timeout_is_valid

        assert not timeout_is_valid(value)
