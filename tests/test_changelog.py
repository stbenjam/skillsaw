"""Release publication: pagination, visibility, migration guidance and refreshes."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "generate_changelog", ROOT / "scripts/generate-changelog.py"
)
changelog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changelog)


def test_release_pages(tmp_path):
    pages = json.loads((ROOT / "tests/fixtures/site/releases.json").read_text())
    (tmp_path / "includes").mkdir()
    (tmp_path / "includes/upgrading-0.20.md").write_text(
        (ROOT / "docs/includes/upgrading-0.20.md").read_text()
    )
    changelog.generate(pages, tmp_path)
    index = (tmp_path / "changelog.md").read_text()
    assert index.index("0.21.0-rc.1") < index.index("0.20.0") < index.index("0.19.0")
    assert "Pre-release" in index
    assert "0.22.0" not in index
    release = (tmp_path / "changelog/0.20.0.md").read_text()
    assert pages[1][0]["body"] in release
    assert "## Upgrade notes" in release
    assert "### Choose when to enable new rules" in release
    assert "](../configuration.md#enabling-rules)" in release
    snapshot = {p: p.read_text() for p in tmp_path.rglob("*.md")}
    changelog.generate(pages, tmp_path)
    assert snapshot == {p: p.read_text() for p in tmp_path.rglob("*.md")}
    # Deleted releases disappear without removing hand-authored files.
    custom = tmp_path / "changelog/custom.md"
    custom.write_text("Editorial notes")
    changelog.generate([pages[0]], tmp_path)
    assert not (tmp_path / "changelog/0.20.0.md").exists()
    assert custom.read_text() == "Editorial notes"


def test_unsafe_tag_leaves_existing_pages_unchanged(tmp_path):
    destination = tmp_path / "changelog"
    destination.mkdir()
    existing = destination / "0.19.0.md"
    existing.write_text(changelog.HEADER + "Existing release")
    with pytest.raises(ValueError, match="Unsupported release tag"):
        changelog.generate(
            [[{"tag_name": "../escape", "draft": False, "published_at": "2026-09-06"}]], tmp_path
        )
    assert existing.read_text() == changelog.HEADER + "Existing release"
