"""Tests for action/review.py diff parsing."""

import sys
from pathlib import Path
from unittest.mock import patch

# action/ is not a package, so add it to sys.path for import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "action"))

import review  # noqa: E402


def _fake_api_with_patch(patch_text):
    """Return a github_api callable that returns a single file with the given patch."""

    def fake_github_api(method, url):
        # Only return data for page 1; use endswith to avoid matching page=10, etc.
        if url.endswith("page=1"):
            return [{"filename": "file.txt", "patch": patch_text}]
        # All other pages return empty list to end pagination
        return []

    return fake_github_api


class TestGetDiffInfoNoNewline:
    """Verify that '\\ No newline at end of file' markers don't shift line numbers."""

    def test_no_newline_marker_does_not_increment_line(self):
        # A patch where the last added line has no trailing newline.
        # The hunk starts at new-file line 1, adds three lines, and the
        # third line is followed by the no-newline marker.
        patch_text = (
            "@@ -0,0 +1,3 @@\n"
            "+line one\n"
            "+line two\n"
            "+line three\n"
            "\\ No newline at end of file"
        )

        with patch.object(review, "github_api", new=_fake_api_with_patch(patch_text)):
            _, diff_lines = review.get_diff_info("owner/repo", "1")

        # Lines 1, 2, 3 should be recorded -- the no-newline marker must not
        # create a spurious line 4.
        assert ("file.txt", 1) in diff_lines
        assert ("file.txt", 2) in diff_lines
        assert ("file.txt", 3) in diff_lines
        assert ("file.txt", 4) not in diff_lines

    def test_no_newline_marker_mid_hunk(self):
        # Simulate a diff where a deletion's no-newline marker appears before
        # subsequent additions.  The added line after the marker must still get
        # the correct line number.
        patch_text = (
            "@@ -1,3 +1,3 @@\n"
            " context line\n"
            "-old line\n"
            "\\ No newline at end of file\n"
            "+new line\n"
            " final context"
        )

        with patch.object(review, "github_api", new=_fake_api_with_patch(patch_text)):
            _, diff_lines = review.get_diff_info("owner/repo", "1")

        # context line -> line 1 (incremented to 2)
        # -old line   -> skipped
        # \ No newline -> skipped (should NOT increment)
        # +new line   -> line 2 (incremented to 3)
        # final context -> line 3
        assert ("file.txt", 2) in diff_lines  # +new line
        assert ("file.txt", 1) not in diff_lines  # context only, not addition
