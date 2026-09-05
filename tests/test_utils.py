"""
Tests for builtin rule utilities (read_text, read_json, frontmatter_key_line, heading_line,
and centralized YAML line number functions).
"""

import json
import os
from pathlib import Path
import stat

import pytest

from skillsaw import utils as skillsaw_utils
from skillsaw.utils import (
    mkdir_parents_anchored,
    read_toml,
    rename_path_anchored,
    write_bytes_atomic,
)

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


def test_read_toml_parses_valid(temp_dir):
    f = temp_dir / "config.toml"
    f.write_text('[mcp_servers.berths]\ncommand = "bin/harbourmaster"\n', encoding="utf-8")
    data, error = read_toml(f)
    assert data == {"mcp_servers": {"berths": {"command": "bin/harbourmaster"}}}
    assert error is None


def test_read_toml_returns_error_on_syntax_error(temp_dir):
    """The parser's own wording carries the position this two-element
    contract cannot; what is pinned is that an error came back, not how
    ``tomli`` phrases it — the 3.9 floor resolves a separately versioned
    copy."""
    f = temp_dir / "bad.toml"
    f.write_text("[mcp_servers.berths\n", encoding="utf-8")
    data, error = read_toml(f)
    assert data is None
    assert "line 1" in error


def test_read_toml_returns_error_on_duplicate_key(temp_dir):
    """A duplicate key is a parse error in TOML, not a last-one-wins merge as
    it is in the JSON readers."""
    f = temp_dir / "dup.toml"
    f.write_text("[mcp]\nmax_output_bytes = 1\nmax_output_bytes = 2\n", encoding="utf-8")
    data, error = read_toml(f)
    assert data is None
    assert "Cannot overwrite a value" in error


def test_read_toml_returns_error_on_duplicate_table_header(temp_dir):
    f = temp_dir / "dup-table.toml"
    f.write_text(
        '[mcp_servers.berths]\ncommand = "a"\n\n[mcp_servers.berths]\ncommand = "b"\n',
        encoding="utf-8",
    )
    data, error = read_toml(f)
    assert data is None
    assert "Cannot declare" in error


def test_read_toml_accepts_a_utf8_bom(temp_dir):
    """``read_text`` decodes with ``utf-8-sig``, so the mark never reaches the
    parser — which would refuse it. Whether Grok's Rust reader refuses one is
    unmeasured, so this stays permissive rather than inventing a verdict."""
    f = temp_dir / "bom.toml"
    f.write_bytes(b"\xef\xbb\xbf" + b'[permission]\nallow = ["Bash(make test)"]\n')
    data, error = read_toml(f)
    assert error is None
    assert data == {"permission": {"allow": ["Bash(make test)"]}}


def test_read_toml_returns_error_on_missing(temp_dir):
    data, error = read_toml(temp_dir / "missing.toml")
    assert data is None
    assert "Failed to read" in error


def test_read_toml_returns_error_on_undecodable_bytes(temp_dir):
    """A config saved as cp1252 never reaches the parser: ``read_text``
    refuses it, and the reader reports rather than raising."""
    f = temp_dir / "cp1252.toml"
    f.write_bytes(b'[permission]\nallow = ["Bash(caf\x92 *)"]\n')
    data, error = read_toml(f)
    assert data is None
    assert "Failed to read" in error


def test_read_toml_reports_deep_nesting(temp_dir):
    """A ``RecursionError`` from the parser becomes an error string; escaping
    it would abort the whole lint."""
    f = temp_dir / "deep.toml"
    f.write_text("a = " + "[" * 2000 + "]" * 2000, encoding="utf-8")
    assert read_toml(f) == (None, "Nesting too deep to parse")


def test_read_toml_reports_an_oversized_integer(temp_dir, oversized_integer_digits):
    """Past the interpreter's digit limit the parser raises bare
    ``ValueError``, not its own decode error."""
    if oversized_integer_digits is None:
        pytest.skip("interpreter enforces no int-parse digit limit")
    f = temp_dir / "big.toml"
    f.write_text(f"a = {oversized_integer_digits}\n", encoding="utf-8")
    data, error = read_toml(f)
    assert data is None
    assert "digits" in error


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


def test_yaml_path_line_lookup_deep_nesting_does_not_crash():
    depth = 250
    text = "root:\n" + "".join("  " * (index + 1) + "nested:\n" for index in range(depth))
    text += "  " * (depth + 1) + "value\n"

    lookup = yaml_path_line_lookup(text)

    assert lookup("root") is None


@pytest.mark.parametrize("error_type", [ValueError, RecursionError])
def test_yaml_path_line_lookup_handles_ruamel_runtime_errors(monkeypatch, error_type):
    class BrokenYaml:
        preserve_quotes = False

        def load(self, _text):
            raise error_type("parser failed")

    monkeypatch.setattr(skillsaw_utils, "_RuamelYAML", BrokenYaml)

    lookup = yaml_path_line_lookup("name: test\n")

    assert lookup("name") is None


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


def test_parse_frontmatter_recursion_is_reported_as_invalid(monkeypatch):
    # Simulate a RecursionError during YAML loading to verify error handling
    # without depending on environment-specific stack limits.
    import yaml as yaml_mod

    def explode(*_args, **_kwargs):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(yaml_mod, "load", explode)
    content = "---\nextra: [[0]]\n---\nbody\n"
    frontmatter, body, error_line = parse_frontmatter(content)

    assert frontmatter is None
    assert body == content
    assert error_line is None


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

    @pytest.mark.parametrize(
        "comment",
        ["// 文档 😀\r\n", "/* 文档\r\n😀\n */", "/* */\n// 第二条\n"],
    )
    def test_unicode_comment_offsets_and_adjacent_trailing_comma(self, comment):
        from skillsaw.utils import strip_jsonc

        prefix = '{"标题": "😀 // keep", "items": ["é",'
        source = prefix + comment + '], "value": }'
        stripped = strip_jsonc(source)
        assert len(stripped) == len(source)
        assert stripped[: len(prefix) - 1] == prefix[:-1]
        assert stripped[len(prefix) - 1] == " "
        assert [i for i, char in enumerate(stripped) if char == "\n"] == [
            i for i, char in enumerate(source) if char == "\n"
        ]
        with pytest.raises(json.JSONDecodeError) as failure:
            json.loads(stripped)
        assert failure.value.pos == source.rindex("}")
        assert failure.value.lineno == source.count("\n") + 1
        assert failure.value.colno == len(source.rsplit("\n", 1)[-1])

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

    @pytest.mark.parametrize("allow_duplicate_keys", [False, True])
    def test_read_jsonc_rejects_the_non_finite_extension(self, tmp_path, allow_duplicate_keys):
        from skillsaw.utils import read_jsonc

        path = tmp_path / "opencode.jsonc"
        path.write_text('{"timeout": NaN}')
        data, error = read_jsonc(path, allow_duplicate_keys=allow_duplicate_keys)
        assert data is None
        assert "NaN" in error

    @pytest.mark.parametrize(
        "content",
        [
            '{"name": "first", "name": "second"}',
            '{// comment\n"nested": {"name": 1, "name": 2},}',
        ],
    )
    def test_read_jsonc_rejects_duplicate_object_keys(self, tmp_path, content):
        from skillsaw.utils import read_jsonc

        path = tmp_path / "opencode.jsonc"
        path.write_text(content)

        data, error = read_jsonc(path)

        assert data is None
        assert 'duplicate JSON object key: "name"' in error

    @pytest.mark.parametrize("comment", ["", "// Registry metadata\n"])
    def test_duplicate_key_policy_is_explicit_and_cached_separately(self, tmp_path, comment):
        from skillsaw.blocks.json_config import OpenCodeConfigBlock
        from skillsaw.utils import read_jsonc

        path = tmp_path / "config.jsonc"
        path.write_text(comment + '{"name":"first","name":"second"}')
        assert read_jsonc(path, allow_duplicate_keys=True) == ({"name": "second"}, None)
        data, error = read_jsonc(path)
        assert data is None
        assert 'duplicate JSON object key: "name"' in error
        assert read_jsonc(path, allow_duplicate_keys=True) == ({"name": "second"}, None)
        # Enabling Antigravity's policy must not relax another JSONC host.
        block = OpenCodeConfigBlock(path=path)
        assert block.raw_data is None
        assert 'duplicate JSON object key: "name"' in block.parse_error


def test_read_json_strict_rejects_duplicate_object_keys(tmp_path):
    from skillsaw.utils import read_json_strict

    path = tmp_path / "skills-lock.json"
    path.write_text('{"skills": {"demo": {"source": "one", "source": "two"}}}')

    data, error = read_json_strict(path)

    assert data is None
    assert 'duplicate JSON object key: "source"' in error


def test_rule_strict_json_rejects_duplicate_object_keys(tmp_path):
    from skillsaw.rules.builtin.utils import strict_json

    path = tmp_path / "plugin.json"
    path.write_text('{"name": "first", "name": "second"}')

    data, error = strict_json(path)

    assert data is None
    assert 'duplicate JSON object key: "name"' in error


@pytest.mark.parametrize(
    "key",
    [
        "\x1b]0;unsafe\x07" + "x" * 1000,
        "😀" * 100,
        "é" * 100,
        "\x00" * 100,
        "\u202e" * 100,
        "\ud800" * 100,
    ],
    ids=["terminal-control", "emoji", "non-ascii", "nul", "bidi", "lone-surrogate"],
)
def test_duplicate_json_key_diagnostic_is_bounded_and_control_safe(tmp_path, key):
    from skillsaw.utils import read_json_strict

    path = tmp_path / "server.json"
    path.write_text(json.dumps({key: 1})[:-1] + "," + json.dumps(key) + ":2}")

    data, error = read_json_strict(path)

    assert data is None
    assert "\x1b" not in error
    assert len(error) < 200
    error.encode("utf-8")


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
