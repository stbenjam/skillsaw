"""Focused tests for OpenCode configured-instruction discovery."""

from collections import Counter
from pathlib import Path

from skillsaw.discovery import opencode


def _matches_by_pattern(root: Path, patterns: list[str]) -> dict[int, list[str]]:
    matches = {index: [] for index in range(len(patterns))}
    for pattern_index, path in opencode.contained_instruction_globs(
        root,
        root,
        patterns,
        lambda _path: False,
    ):
        matches[pattern_index].append(path.relative_to(root).as_posix())
    return matches


def test_instruction_globs_preserve_component_and_double_star_matching(tmp_path):
    root = tmp_path.resolve()
    for relative in (
        "other.md",
        "docs/guide.md",
        "docs/api/guide1.md",
        "docs/api/deep/guide2.md",
        "docs/api/deep/other.txt",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("instructions\n")

    patterns = [
        "docs/guide.md",
        "docs/*.md",
        "docs/**/guide?.md",
        "docs/[g]uide.md",
        "**/*.md",
        "../outside/*.md",
        str(root / "docs" / "*.md"),
    ]

    assert _matches_by_pattern(root, patterns) == {
        0: ["docs/guide.md"],
        1: ["docs/guide.md"],
        2: ["docs/api/deep/guide2.md", "docs/api/guide1.md"],
        3: ["docs/guide.md"],
        4: [
            "docs/api/deep/guide2.md",
            "docs/api/guide1.md",
            "docs/guide.md",
            "other.md",
        ],
        5: [],
        6: [],
    }


def test_recursive_instruction_patterns_scan_each_directory_once(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    for relative in ("a/one", "a/two/deep", "b"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "a" / "guide.md").write_text("instructions\n")
    expected_directories = {root, *(path for path in root.rglob("*") if path.is_dir())}

    real_scandir = opencode.os.scandir
    scanned = []

    def counting_scandir(path):
        scanned.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(opencode.os, "scandir", counting_scandir)
    patterns = [f"**/missing-{index}.md" for index in range(32)] + ["**/*.md"]

    matches = list(
        opencode.contained_instruction_globs(
            root,
            root,
            patterns,
            lambda _path: False,
        )
    )

    assert matches == [(32, root / "a" / "guide.md")]
    counts = Counter(scanned)
    assert set(counts) == expected_directories
    assert set(counts.values()) == {1}


def test_instruction_globs_keep_scan_failures_scoped_to_affected_patterns(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    for relative in ("good/keep.md", "bad/drop.md"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("instructions\n")

    real_scandir = opencode.os.scandir

    def failing_scandir(path):
        if Path(path) == root / "bad":
            raise PermissionError(path)
        return real_scandir(path)

    monkeypatch.setattr(opencode.os, "scandir", failing_scandir)

    assert _matches_by_pattern(root, ["good/*.md", "**/*.md"]) == {
        0: ["good/keep.md"],
        1: [],
    }
