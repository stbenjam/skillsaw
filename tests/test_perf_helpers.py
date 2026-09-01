"""
Tests for the performance helpers added with the benchmark framework:

- ``_required_literal`` / ``patterns_matching_anywhere`` (regex prefilter)
- ``frontmatter_line_map_top_level`` and its libyaml fast path
- ``LintTarget.find()`` memoization and invalidation
"""

import re
from pathlib import Path

import pytest

from skillsaw.rules.builtin.content_analysis import (
    _gate_pattern,
    _required_literal,
    _required_literal_sets,
    patterns_matching_anywhere,
    FrontmatterField,
)
from skillsaw.rules.builtin.utils import (
    _fast_top_level_key_lines,
    frontmatter_key_line,
    frontmatter_line_map_top_level,
    invalidate_read_caches,
)


class TestRequiredLiteral:
    def test_simple_phrase(self):
        assert _required_literal(r"\btry to\b", re.IGNORECASE) == "try to"

    def test_longest_run_wins(self):
        assert _required_literal(r"\bsk-[a-zA-Z0-9]{20,}", 0) == "sk-"
        assert _required_literal(r"\bconsider\s+(?:using|adding)\b", re.IGNORECASE) == "consider"

    def test_anchors_are_transparent(self):
        # \b is zero-width: literals around it stay contiguous
        assert _required_literal(r"\bgpt-3\.5\b", re.IGNORECASE) == "gpt-3.5"

    def test_branch_only_pattern_has_no_literal(self):
        assert _required_literal(r"(?:foo|bar)", 0) is None

    def test_short_literal_rejected(self):
        assert _required_literal(r"\bSK[0-9a-fA-F]{32}", 0) is None

    def test_invalid_pattern_returns_none(self):
        assert _required_literal(r"(unclosed", 0) is None

    def test_literal_lowercased(self):
        assert _required_literal(r"\bAKIA[0-9A-Z]{16}", 0) == "akia"

    @pytest.mark.parametrize(
        "pattern,flags,text",
        [
            (r"\btry to\b", re.IGNORECASE, "Please TRY TO do this"),
            (r"\bsk-[a-zA-Z0-9]{20,}", 0, "key sk-" + "a" * 24),  # notsecret
            (r"(?i)\bpassword\s*[=:]\s*['\"][^'\"]{8,}['\"]", 0, 'password = "hunter2hunter2"'),
            (r"\bconsider\s+(?:using|adding)\b", re.IGNORECASE, "Consider using X"),
        ],
    )
    def test_literal_present_in_every_match(self, pattern, flags, text):
        """Core safety property: if the regex matches, the literal must appear."""
        compiled = re.compile(pattern, flags)
        literal = _required_literal(pattern, compiled.flags)
        assert compiled.search(text)
        assert literal is not None
        assert literal in text.lower()


class TestRequiredLiteralSets:
    """Tests for extracting sets of required literals from regex patterns."""

    def test_single_run_is_a_one_member_set(self):
        assert _required_literal_sets(r"\btry to\b", re.IGNORECASE) == (("try to",),)

    def test_every_top_level_run_is_required(self):
        # "api" and "key" are separated by an optional character class, so both
        # literal runs must appear in any match.
        assert _required_literal_sets(r"(?i)\bapi[_-]?key\s*[=:]", 0) == (("api",), ("key",))

    def test_alternation_yields_one_set_of_alternatives(self):
        assert _required_literal_sets(
            r"\b(semicolons?|trailing commas?|single quotes?)\b", re.IGNORECASE
        ) == (
            ("semicolon", "trailing comma", "single quote"),
        )
        assert _required_literal_sets(r"(?:foo|bar)", 0) == (("foo", "bar"),)

    def test_branches_and_runs_combine(self):
        sets = _required_literal_sets(
            r"\b(?:get|obtain|require)s?\s+(?:approval|confirmation|permission)\b(?!\s+x)",
            re.IGNORECASE,
        )
        assert sets == (("get", "obtain", "require"), ("approval", "confirmation", "permission"))

    def test_alternative_without_literal_drops_the_set(self):
        assert _required_literal_sets(r"(a|)", 0) == ()
        assert _required_literal_sets(r"(?:foo|[0-9]+)", 0) == ()

    def test_short_or_invalid_yields_nothing(self):
        assert _required_literal_sets(r"\bSK[0-9a-fA-F]{32}", 0) == ()
        assert _required_literal_sets(r"(unclosed", 0) == ()

    @pytest.mark.parametrize(
        "pattern,flags,text",
        [
            (r"\b(semicolons?|trailing commas?)\b", re.IGNORECASE, "Use Semicolons everywhere"),
            (r"\b(?:get|require)s?\s+(?:approval|permission)\b", re.IGNORECASE, "Get approval"),
            (
                r"(?i)\bapi[_-]?key\s*[=:]\s*['\"][^'\"]{16,}['\"]",
                0,
                'API-KEY = "abcdefghijklmnopq"',
            ),
        ],
    )
    def test_every_set_is_satisfied_by_every_match(self, pattern, flags, text):
        compiled = re.compile(pattern, flags)
        assert compiled.search(text)
        lowered = text.lower()
        for alternatives in _required_literal_sets(pattern, compiled.flags):
            assert any(literal in lowered for literal in alternatives)


class TestGatePattern:
    def test_leading_boundary_is_stripped(self):
        gate = _gate_pattern(re.compile(r"\bsk-[a-z]{3}"))
        assert gate.pattern == r"sk-[a-z]{3}"

    def test_inline_flags_are_kept_ahead_of_the_boundary(self):
        gate = _gate_pattern(re.compile(r"(?i)\bpassword\s*="))
        assert gate.pattern == r"(?i)password\s*="
        assert gate.search("PASSWORD =")

    def test_pattern_without_leading_boundary_is_returned_as_is(self):
        pattern = re.compile(r"x\by")
        assert _gate_pattern(pattern) is pattern

    def test_gate_is_a_superset_of_the_pattern(self):
        pattern = re.compile(r"\bcat\b")
        gate = _gate_pattern(pattern)
        for text in ("a cat", "concatenate", "cats", "dog"):
            if pattern.search(text):
                assert gate.search(text)


class TestPatternsMatchingAnywhere:
    PATTERNS = [
        (re.compile(r"\btry to\b", re.IGNORECASE), "hedging"),
        (re.compile(r"\bperhaps\b", re.IGNORECASE), "hedging"),
        (re.compile(r"\bproperly\b", re.IGNORECASE), "vagueness"),
    ]

    def test_no_match_returns_empty(self):
        assert patterns_matching_anywhere("clean direct text", self.PATTERNS) == []

    def test_subset_preserves_order(self):
        text = "you should properly try to do this"
        active = patterns_matching_anywhere(text, self.PATTERNS)
        assert [t[1] for t in active] == ["hedging", "vagueness"]
        assert active[0] is self.PATTERNS[0]

    def test_identical_to_naive_filter(self):
        texts = [
            "Try To start, perhaps",
            "do it properly",
            "",
            "TRY TO\nproperly\nperhaps",
            "nothing here",
        ]
        for text in texts:
            naive = [t for t in self.PATTERNS if t[0].search(text)]
            assert patterns_matching_anywhere(text, self.PATTERNS) == naive

    def test_pattern_without_literal_still_checked(self):
        patterns = [(re.compile(r"(?:ab|cd)"), "branchy")]
        assert patterns_matching_anywhere("xxabxx", patterns) == patterns
        assert patterns_matching_anywhere("xxxx", patterns) == []

    def test_identical_to_naive_filter_across_prefilter_shapes(self):
        """Verify the prefilter produces identical results to testing the full regex."""
        patterns = [
            (re.compile(r"\b(semicolons?|trailing commas?)\b", re.IGNORECASE), "alt"),
            (re.compile(r"\b(?:get|require)s?\s+(?:approval|permission)\b", re.IGNORECASE), "two"),
            (re.compile(r"(?i)\bapi[_-]?key\s*[=:]"), "runs"),
            (re.compile(r"\bSK[0-9a-fA-F]{32}"), "gate-only"),
            (re.compile(r"(?:ab|[0-9]+)"), "no-literal"),
        ]
        texts = [
            "Use semicolons; get approval; API_KEY=1; SK" + "a" * 32,
            "trailing comma, requires permission",
            "get permission but no api key here",
            "apikey: x  (no separator match)",
            "the word getapproval has no space",
            "SK" + "0" * 31,
            "",
            "xx ab 12",
        ]
        for text in texts:
            naive = [t for t in patterns if t[0].search(text)]
            assert patterns_matching_anywhere(text, patterns) == naive, text


class TestFastTopLevelKeyLines:
    def test_simple_mapping(self):
        result = _fast_top_level_key_lines("name: x\ndescription: y\n")
        assert result == {"name": 0, "description": 1}

    def test_multiline_and_quoted_values(self):
        text = 'name: "quoted: colon"\ndescription: |\n  line one\n  line two\nversion: 1\n'
        result = _fast_top_level_key_lines(text)
        assert result == {"name": 0, "description": 1, "version": 4}

    def test_duplicate_keys_fall_back(self):
        assert _fast_top_level_key_lines("a: 1\na: 2\n") is None

    def test_non_string_keys_fall_back(self):
        assert _fast_top_level_key_lines("1: x\n") is None
        assert _fast_top_level_key_lines("true: x\n") is None

    def test_non_mapping_document(self):
        assert _fast_top_level_key_lines("- a\n- b\n") == {}
        assert _fast_top_level_key_lines("") == {}

    def test_parse_error_falls_back(self):
        assert _fast_top_level_key_lines("a: [unclosed\nb: }{\n") is None


class TestFrontmatterLineMap:
    def _write(self, tmp_path, content):
        f = tmp_path / "SKILL.md"
        f.write_text(content, encoding="utf-8")
        invalidate_read_caches()
        return f

    def test_basic_map(self, tmp_path):
        f = self._write(tmp_path, "---\nname: x\ndescription: y\n---\n\n# Body\n")
        assert frontmatter_line_map_top_level(f) == {"name": 2, "description": 3}
        assert frontmatter_key_line(f, "description") == 3
        assert frontmatter_key_line(f, "missing") is None

    def test_no_frontmatter(self, tmp_path):
        f = self._write(tmp_path, "# Just a heading\n")
        assert frontmatter_line_map_top_level(f) == {}
        assert frontmatter_key_line(f, "name") is None

    def test_fast_path_matches_ruamel_fallback(self, tmp_path, monkeypatch):
        content = (
            "---\n"
            'name: "test: skill"\n'
            "description: >\n"
            "  folded text\n"
            "  more text\n"
            "metadata:\n"
            "  nested: true\n"
            "tags: [a, b]\n"
            "---\n\nbody\n"
        )
        f = self._write(tmp_path, content)
        fast = frontmatter_line_map_top_level(f)

        # Patch the core module where the implementation lives — the
        # rules.builtin.utils shim only re-exports a binding, so patching it
        # would not reach the call site inside skillsaw.utils.
        from skillsaw import utils

        monkeypatch.setattr(utils, "_fast_top_level_key_lines", lambda text: None)
        invalidate_read_caches()
        slow = frontmatter_line_map_top_level(f)
        assert (
            fast
            == slow
            == {
                "name": 2,
                "description": 3,
                "metadata": 6,
                "tags": 8,
            }
        )

    def test_duplicate_keys_yield_no_lines(self, tmp_path):
        # ruamel rejects duplicate keys, so no line info is available —
        # matching the pre-optimization behavior.
        f = self._write(tmp_path, "---\nname: a\nname: b\n---\nbody\n")
        assert frontmatter_key_line(f, "name") is None


class TestFrontmatterSuppressionWithFastPath:
    """Inline suppression of frontmatter-field violations must work the same
    through the libyaml line-map fast path and the ruamel fallback.

    Suppression directives are YAML ``#`` comments scanned from raw text —
    they never pass through a YAML parser — but they suppress by *file line*,
    and frontmatter violation lines come from frontmatter_key_line().
    """

    _SECRET_FM = (
        "---\n"
        "name: demo-skill\n"
        "{directive}"
        "description: Use token ghp_" + "abcd" * 10 + " when calling the demo API\n"  # notsecret
        "---\n\n# Demo Skill\n\nA demo skill body.\n"
    )

    def _run(self, tmp_path, directive, monkeypatch, fast):
        from skillsaw.context import RepositoryContext
        from skillsaw.linter import Linter
        from skillsaw.config import LinterConfig

        # Patch core skillsaw.utils (not the rules.builtin.utils shim) so the
        # forced ruamel-fallback actually reaches the implementation call site.
        from skillsaw import utils

        skill = tmp_path / "skills" / "demo-skill"
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(
            self._SECRET_FM.format(directive=directive), encoding="utf-8"
        )
        invalidate_read_caches()
        if not fast:
            monkeypatch.setattr(utils, "_fast_top_level_key_lines", lambda text: None)
        linter = Linter(
            RepositoryContext(tmp_path),
            LinterConfig.default(),
            rule_ids={"content-embedded-secrets"},
        )
        violations = linter.run()
        monkeypatch.undo()
        return violations

    @pytest.mark.parametrize("fast", [True, False], ids=["libyaml", "ruamel"])
    def test_directive_suppresses_frontmatter_violation(self, tmp_path, monkeypatch, fast):
        directive = "# skillsaw-disable-next-line content-embedded-secrets\n"
        assert self._run(tmp_path, directive, monkeypatch, fast) == []

    @pytest.mark.parametrize("fast", [True, False], ids=["libyaml", "ruamel"])
    def test_violation_fires_without_directive(self, tmp_path, monkeypatch, fast):
        violations = self._run(tmp_path, "", monkeypatch, fast)
        assert [v.rule_id for v in violations] == ["content-embedded-secrets"]
        assert violations[0].file_line == 3


class TestBrokenReferenceWalkCache:
    def test_repo_walked_at_most_once_per_check(self, tmp_path, monkeypatch):
        """Regression: the repo walk used to run once per broken link, making
        large repos with many broken links effectively unlintable."""
        from skillsaw.context import RepositoryContext
        from skillsaw.rules.builtin.content.broken_internal_reference import (
            ContentBrokenInternalReferenceRule,
        )

        skill = tmp_path / "skills" / "demo"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: demo\ndescription: Demo skill with broken links\n---\n\n"
            "# Demo\n\n"
            "See [one](./missing-one.md) and [two](./missing-two.md) "
            "and [three](./missing-three.md).\n",
            encoding="utf-8",
        )
        invalidate_read_caches()

        calls = {"n": 0}
        original = ContentBrokenInternalReferenceRule._collect_repo_paths

        def counting(self, root):
            calls["n"] += 1
            return original(self, root)

        monkeypatch.setattr(ContentBrokenInternalReferenceRule, "_collect_repo_paths", counting)
        rule = ContentBrokenInternalReferenceRule()
        violations = rule.check(RepositoryContext(tmp_path))
        assert len(violations) == 3
        assert calls["n"] <= 1


class TestFindCache:
    def _make_skill_repo(self, tmp_path):
        skill = tmp_path / "skills" / "demo"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: demo\ndescription: A demo skill for cache tests\n---\n\n# Demo\n",
            encoding="utf-8",
        )
        invalidate_read_caches()
        from skillsaw.context import RepositoryContext

        return RepositoryContext(tmp_path)

    def test_find_is_stable_across_calls(self, tmp_path):
        context = self._make_skill_repo(tmp_path)
        first = context.lint_tree.find(FrontmatterField)
        second = context.lint_tree.find(FrontmatterField)
        assert first == second
        assert {f.name for f in first} == {"name", "description"}

    def test_find_returns_copy(self, tmp_path):
        context = self._make_skill_repo(tmp_path)
        first = context.lint_tree.find(FrontmatterField)
        first.clear()
        assert len(context.lint_tree.find(FrontmatterField)) == 2

    def test_cache_invalidated_on_frontmatter_rewrite(self, tmp_path):
        from skillsaw.rules.builtin.content_analysis import SkillBlock

        context = self._make_skill_repo(tmp_path)
        tree = context.lint_tree
        assert {f.name for f in tree.find(FrontmatterField)} == {"name", "description"}

        block = tree.find(SkillBlock)[0]
        block.write_frontmatter_text(
            "name: demo\ndescription: A demo skill for cache tests\nversion: 1.0.0\n"
        )
        invalidate_read_caches()
        assert {f.name for f in tree.find(FrontmatterField)} == {
            "name",
            "description",
            "version",
        }

    def test_rebuild_lint_tree_resets_cache(self, tmp_path):
        context = self._make_skill_repo(tmp_path)
        assert len(context.lint_tree.find(FrontmatterField)) == 2
        context.rebuild_lint_tree()
        assert len(context.lint_tree.find(FrontmatterField)) == 2
