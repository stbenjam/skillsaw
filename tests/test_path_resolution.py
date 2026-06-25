"""
Unit tests for CLI path resolution and deduplication logic.

_resolve_lint_paths normalizes CLI input in a single pass:
  - Files resolve to their parent directory
  - Exact duplicate resolved paths are removed
  - Paths nested inside another entry are dropped (the parent's
    RepositoryContext already discovers everything beneath it)
  - Order of first appearance is preserved
"""

from skillsaw.cli._helpers import _resolve_lint_paths

# ── Pass 1: _resolve_lint_paths ────────────────────────────────


class TestResolveSinglePaths:
    """File-to-parent resolution for individual paths."""

    def test_file_resolves_to_parent(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.touch()
        result = _resolve_lint_paths([f])
        assert result == [tmp_path]

    def test_directory_stays_unchanged(self, tmp_path):
        d = tmp_path / "my-skill"
        d.mkdir()
        result = _resolve_lint_paths([d])
        assert result == [d]

    def test_nested_file_resolves_to_immediate_parent(self, tmp_path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        f = nested / "SKILL.md"
        f.touch()
        result = _resolve_lint_paths([f])
        assert result == [nested]


class TestDeduplicateExactPaths:
    """Exact duplicates after resolution are collapsed."""

    def test_same_dir_twice(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        result = _resolve_lint_paths([d, d])
        assert result == [d]

    def test_same_dir_three_times(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        result = _resolve_lint_paths([d, d, d])
        assert result == [d]

    def test_same_file_twice(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        f = d / "SKILL.md"
        f.touch()
        result = _resolve_lint_paths([f, f])
        assert result == [d]

    def test_same_file_three_times(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        f = d / "SKILL.md"
        f.touch()
        result = _resolve_lint_paths([f, f, f])
        assert result == [d]

    def test_file_and_its_parent_dir(self, tmp_path):
        """A file and its parent resolve to the same directory — deduped."""
        d = tmp_path / "skill"
        d.mkdir()
        f = d / "SKILL.md"
        f.touch()
        result = _resolve_lint_paths([f, d])
        assert result == [d]

    def test_parent_dir_and_file_in_it(self, tmp_path):
        """Order reversed: dir first, then file inside it — same result."""
        d = tmp_path / "skill"
        d.mkdir()
        f = d / "SKILL.md"
        f.touch()
        result = _resolve_lint_paths([d, f])
        assert result == [d]


class TestOverlappingPathsDropped:
    """Paths nested inside another entry are redundant — the parent's
    RepositoryContext already discovers everything beneath it.
    """

    def test_child_dropped_when_parent_present(self, tmp_path):
        parent = tmp_path / "repo"
        child = parent / "subdir"
        child.mkdir(parents=True)
        result = _resolve_lint_paths([parent, child])
        assert result == [parent]

    def test_child_first_then_parent_drops_child(self, tmp_path):
        """Order shouldn't matter — child is still redundant."""
        parent = tmp_path / "repo"
        child = parent / "subdir"
        child.mkdir(parents=True)
        result = _resolve_lint_paths([child, parent])
        assert result == [parent]

    def test_deeply_nested_child_dropped(self, tmp_path):
        parent = tmp_path / "repo"
        deep = parent / "a" / "b" / "c"
        deep.mkdir(parents=True)
        result = _resolve_lint_paths([parent, deep])
        assert result == [parent]

    def test_nested_file_dropped_when_parent_present(self, tmp_path):
        """A SKILL.md under a passed directory dedups against that directory."""
        parent = tmp_path / "repo"
        skill = parent / "skills" / "deploy"
        skill.mkdir(parents=True)
        f = skill / "SKILL.md"
        f.touch()
        result = _resolve_lint_paths([parent, f])
        assert result == [parent]

    def test_siblings_both_kept(self, tmp_path):
        """Two siblings under the same parent are not overlapping."""
        parent = tmp_path / "repo"
        a = parent / "skill-a"
        b = parent / "skill-b"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        result = _resolve_lint_paths([a, b])
        assert result == [a, b]

    def test_complex_overlap(self, tmp_path):
        """Mix of overlapping and distinct paths."""
        repo1 = tmp_path / "repo1"
        repo1_sub = repo1 / "skills" / "deploy"
        repo2 = tmp_path / "repo2"
        repo1_sub.mkdir(parents=True)
        repo2.mkdir()
        result = _resolve_lint_paths([repo1, repo1_sub, repo2])
        assert result == [repo1, repo2]


class TestPreservesOrder:
    """First-seen order is preserved after dedup."""

    def test_distinct_dirs_preserve_order(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        c = tmp_path / "c"
        a.mkdir()
        b.mkdir()
        c.mkdir()
        result = _resolve_lint_paths([a, b, c])
        assert result == [a, b, c]

    def test_distinct_files_preserve_order(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (a / "SKILL.md").touch()
        (b / "SKILL.md").touch()
        result = _resolve_lint_paths([a / "SKILL.md", b / "SKILL.md"])
        assert result == [a, b]

    def test_mixed_with_dupes_preserves_first_seen(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (a / "SKILL.md").touch()
        result = _resolve_lint_paths([a / "SKILL.md", b, a / "SKILL.md"])
        assert result == [a, b]


class TestMixedFilesAndDirs:
    """Various combinations of files and directories."""

    def test_dir_then_file(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (b / "SKILL.md").touch()
        result = _resolve_lint_paths([a, b / "SKILL.md"])
        assert result == [a, b]

    def test_file_then_dir(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (a / "SKILL.md").touch()
        result = _resolve_lint_paths([a / "SKILL.md", b])
        assert result == [a, b]

    def test_dir_file_dir(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        c = tmp_path / "c"
        a.mkdir()
        b.mkdir()
        c.mkdir()
        (b / "SKILL.md").touch()
        result = _resolve_lint_paths([a, b / "SKILL.md", c])
        assert result == [a, b, c]

    def test_file_dir_file(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        c = tmp_path / "c"
        a.mkdir()
        b.mkdir()
        c.mkdir()
        (a / "SKILL.md").touch()
        (c / "SKILL.md").touch()
        result = _resolve_lint_paths([a / "SKILL.md", b, c / "SKILL.md"])
        assert result == [a, b, c]


class TestEmptyAndSingleInput:
    """Edge cases for empty and single-element inputs."""

    def test_empty_list(self):
        result = _resolve_lint_paths([])
        assert result == []

    def test_single_dir(self, tmp_path):
        result = _resolve_lint_paths([tmp_path])
        assert result == [tmp_path]

    def test_single_file(self, tmp_path):
        f = tmp_path / "SKILL.md"
        f.touch()
        result = _resolve_lint_paths([f])
        assert result == [tmp_path]


# ── _is_subpath ────────────────────────────────────────────────


from skillsaw.cli._helpers import _is_subpath


class TestIsSubpath:
    """Unit tests for the _is_subpath helper."""

    def test_child_is_subpath_of_parent(self, tmp_path):
        parent = tmp_path / "repo"
        child = parent / "subdir"
        child.mkdir(parents=True)
        assert _is_subpath(child, parent) is True

    def test_deeply_nested_is_subpath(self, tmp_path):
        parent = tmp_path / "repo"
        deep = parent / "a" / "b" / "c"
        deep.mkdir(parents=True)
        assert _is_subpath(deep, parent) is True

    def test_parent_is_not_subpath_of_child(self, tmp_path):
        parent = tmp_path / "repo"
        child = parent / "subdir"
        child.mkdir(parents=True)
        assert _is_subpath(parent, child) is False

    def test_same_path_is_not_subpath(self, tmp_path):
        d = tmp_path / "repo"
        d.mkdir()
        assert _is_subpath(d, d) is False

    def test_siblings_are_not_subpaths(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert _is_subpath(a, b) is False
        assert _is_subpath(b, a) is False

    def test_unrelated_paths_are_not_subpaths(self, tmp_path):
        x = tmp_path / "x"
        y = tmp_path / "completely" / "different"
        x.mkdir()
        y.mkdir(parents=True)
        assert _is_subpath(x, y) is False
        assert _is_subpath(y, x) is False

    def test_similar_name_prefix_not_subpath(self, tmp_path):
        """'repo-extra' is not a child of 'repo' even though the name starts with it."""
        repo = tmp_path / "repo"
        repo_extra = tmp_path / "repo-extra"
        repo.mkdir()
        repo_extra.mkdir()
        assert _is_subpath(repo_extra, repo) is False


# ── _build_merged_context ──────────────────────────────────────


from skillsaw.cli._helpers import _build_merged_context, _MergedContext
from skillsaw.context import RepositoryContext, RepositoryType


class TestBuildMergedContext:
    """Tests for merging multiple RepositoryContexts into one for formatters."""

    def test_single_context_returned_as_is(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        (d / "SKILL.md").touch()
        ctx = RepositoryContext(d)
        result = _build_merged_context([ctx])
        assert result is ctx

    def test_two_contexts_merged(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (a / "SKILL.md").touch()
        (b / "SKILL.md").touch()
        ctx_a = RepositoryContext(a)
        ctx_b = RepositoryContext(b)
        result = _build_merged_context([ctx_a, ctx_b])
        assert isinstance(result, _MergedContext)
        assert result.root_path == tmp_path
        assert ctx_a.repo_types | ctx_b.repo_types == result.repo_types

    def test_merged_root_is_common_ancestor(self, tmp_path):
        a = tmp_path / "projects" / "alpha"
        b = tmp_path / "projects" / "beta"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        ctx_a = RepositoryContext(a)
        ctx_b = RepositoryContext(b)
        result = _build_merged_context([ctx_a, ctx_b])
        assert result.root_path == tmp_path / "projects"

    def test_merged_repo_types_is_union(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (a / "SKILL.md").touch()
        (b / ".claude-plugin").mkdir()
        (b / ".claude-plugin" / "plugin.json").write_text("{}")
        ctx_a = RepositoryContext(a)
        ctx_b = RepositoryContext(b)
        result = _build_merged_context([ctx_a, ctx_b])
        assert RepositoryType.AGENTSKILLS in result.repo_types
        assert RepositoryType.SINGLE_PLUGIN in result.repo_types


class TestMergedContextRepoType:
    """The repo_type property should return the primary type by priority."""

    def test_unknown_when_empty(self, tmp_path):
        ctx = _MergedContext(
            root_path=tmp_path,
            repo_types={RepositoryType.UNKNOWN},
            plugins=[],
            skills=[],
        )
        assert ctx.repo_type == RepositoryType.UNKNOWN

    def test_returns_highest_priority(self, tmp_path):
        ctx = _MergedContext(
            root_path=tmp_path,
            repo_types={RepositoryType.AGENTSKILLS, RepositoryType.DOT_CLAUDE},
            plugins=[],
            skills=[],
        )
        assert ctx.repo_type != RepositoryType.UNKNOWN


# ── _dedup_rules ───────────────────────────────────────────────


from skillsaw.cli._helpers import _dedup_rules


class _FakeRule:
    """Minimal rule-like object for testing _dedup_rules."""

    def __init__(self, rule_id):
        self.rule_id = rule_id


class TestDedupRules:

    def test_no_dupes_unchanged(self):
        rules = [_FakeRule("a"), _FakeRule("b"), _FakeRule("c")]
        result = _dedup_rules(rules)
        assert [r.rule_id for r in result] == ["a", "b", "c"]

    def test_duplicates_collapsed(self):
        rules = [_FakeRule("a"), _FakeRule("b"), _FakeRule("a")]
        result = _dedup_rules(rules)
        assert [r.rule_id for r in result] == ["a", "b"]

    def test_all_same_collapses_to_one(self):
        rules = [_FakeRule("x"), _FakeRule("x"), _FakeRule("x")]
        result = _dedup_rules(rules)
        assert [r.rule_id for r in result] == ["x"]

    def test_empty_list(self):
        assert _dedup_rules([]) == []

    def test_preserves_first_occurrence(self):
        r1 = _FakeRule("a")
        r2 = _FakeRule("a")
        result = _dedup_rules([r1, r2])
        assert result[0] is r1
