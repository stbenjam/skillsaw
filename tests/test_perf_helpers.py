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
    _required_literal,
    case_fold,
    literal_alternation,
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


class TestCaseFoldedGate:
    """The gate has to fold text the way ``re.IGNORECASE`` compares it.

    ``str.lower`` leaves U+017F (long s) alone while the regex engine
    matches it against "s", so a gate built on it silently drops a
    document the pattern does match.
    """

    PATTERN = re.compile(r"\buse\s+tabs\b", re.IGNORECASE)

    @pytest.mark.parametrize(
        "text",
        [
            "use tabs",
            "uſe tabs",  # U+017F LATIN SMALL LETTER LONG S
            "USE TABS",
        ],
    )
    def test_a_matching_document_survives_the_gate(self, text):
        assert self.PATTERN.search(text), "precondition: the regex matches"
        assert patterns_matching_anywhere(text, [(self.PATTERN, "x")]) == [(self.PATTERN, "x")]

    def test_capital_dotted_i_is_normalized(self):
        """``casefold`` turns U+0130 into "i" plus a combining dot.

        ``re.IGNORECASE`` matches it against a plain "i", so without the
        rewrite the gate drops a document the pattern does match.
        """
        pattern = re.compile(r"\bkilo\b", re.IGNORECASE)
        text = "one KİLO of it"  # U+0130 LATIN CAPITAL LETTER I WITH DOT ABOVE

        assert pattern.search(text), "precondition: the regex matches"
        assert case_fold("K\u0130LO") == "kilo"
        assert patterns_matching_anywhere(text, [(pattern, "x")]) == [(pattern, "x")]

    def test_dotless_i_is_normalized(self):
        """U+0131 is the one codepoint ``casefold`` alone does not close.

        ``re.IGNORECASE`` matches it against "i" in both directions, but
        ``"kılo".casefold()`` is still ``"kılo"``.
        """
        pattern = re.compile(r"\bkilo\b", re.IGNORECASE)
        text = "one kılo of it"  # U+0131 LATIN SMALL LETTER DOTLESS I

        assert pattern.search(text), "precondition: the regex matches"
        assert case_fold("k\u0131lo") == "kilo"
        assert patterns_matching_anywhere(text, [(pattern, "x")]) == [(pattern, "x")]

    def test_a_document_without_the_literal_is_still_rejected(self):
        assert patterns_matching_anywhere("nothing relevant here", [(self.PATTERN, "x")]) == []


class TestLiteralAlternation:
    def test_matches_every_word_it_was_given(self):
        source = literal_alternation(("always", "never", "do not"))
        pattern = re.compile("(?:%s)$" % source)

        for word in ("always", "never", "do not"):
            assert pattern.match(word), word
        assert not pattern.match("sometimes")

    def test_a_word_that_prefixes_another_still_matches(self):
        """The shared-prefix factoring must not swallow the shorter word.

        Grouping the continuation is what separates ``do(?:wnload)?`` from
        ``download?``, which matches "download" but not "do".
        """
        pattern = re.compile("(?:%s)$" % literal_alternation(("do", "download")))

        assert pattern.match("do")
        assert pattern.match("download")
        assert not pattern.match("dow")

    def test_matches_the_same_language_as_a_flat_alternation(self):
        words = ("set", "setting", "settings", "sets", "run", "runner")
        factored = re.compile("(?:%s)$" % literal_alternation(words), re.IGNORECASE)
        flat = re.compile("(?:%s)$" % "|".join(words), re.IGNORECASE)

        for candidate in words + ("se", "setti", "runn", "", "RUN", "Settings"):
            assert bool(factored.match(candidate)) == bool(flat.match(candidate)), candidate


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
        "description: Use token ghp_" + "a" * 40 + " when calling the demo API\n"  # notsecret
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

    def test_rebuild_lint_tree_drops_stale_path_resolutions(self, tmp_path):
        """A rebuild is the declared "the filesystem may have moved" seam.

        It clears the Promptfoo walk for that reason, and it has to clear
        the resolution memo for the same one: a caller who retargets a
        symlink and rebuilds would otherwise get containment and
        discovery answers keyed on the old target.
        """
        import skillsaw.paths as paths

        context = self._make_skill_repo(tmp_path)
        old = tmp_path / "old"
        new = tmp_path / "new"
        old.mkdir()
        new.mkdir()
        link = tmp_path / "link"
        link.symlink_to(old)

        assert paths.safe_resolve(link) == old.resolve()
        link.unlink()
        link.symlink_to(new)
        # Still the pre-move answer, which is the memo working as intended.
        assert paths.safe_resolve(link) == old.resolve()

        context.rebuild_lint_tree()

        assert paths.safe_resolve(link) == new.resolve()

    def test_find_filtered_stores_into_the_live_cache(self, tmp_path):
        """Anything that drops the memo mid-call detaches the dict.

        ``find()`` learned this the hard way: its walk can parse a block's
        frontmatter for the first time, and building that block's children
        drops ``_find_cache`` from this node and every ancestor, so a dict
        captured before the walk is orphaned by the time the result is
        written into it. The tree builder happens to parse every block
        today, so ``find_filtered`` cannot reach that path through
        ``find()`` — but it shares the invariant, and the predicate it
        runs is caller-supplied. Invalidating from the predicate is the
        direct way to hold it to the contract.
        """
        context = self._make_skill_repo(tmp_path)
        tree = context.lint_tree

        def predicate(field):
            tree.invalidate_find_cache()
            return field.name == "name"

        found = tree.find_filtered(FrontmatterField, "named", predicate)

        assert [f.name for f in found] == ["name"]
        assert (FrontmatterField, "named") in tree.__dict__.get(
            "_find_cache", {}
        ), "the result was written into a cache dict already detached from the node"


class TestSourceRelativeDirectory:
    """The skill-relative directory of a source, used to build the needles
    a mention is matched against."""

    @staticmethod
    def _rel(relative_source):
        from skillsaw.rules.builtin.agentskills.unreferenced_files import (
            AgentSkillUnreferencedFilesRule,
        )

        skill = Path("/skill")
        return AgentSkillUnreferencedFilesRule._source_rel_dir(skill / relative_source, skill)

    def test_a_source_at_the_skill_root_has_no_relative_directory(self):
        assert self._rel("SKILL.md") == ""

    def test_a_nested_source_keeps_its_directory(self):
        assert self._rel("references/guide.md") == "references"

    @pytest.mark.parametrize("directory", ["docs.", ".hidden", "a.b"])
    def test_dots_in_a_directory_name_survive(self, directory):
        """Only the exact value "." means the skill root.

        Stripping dots would rewrite these legal directory names into
        something no candidate path matches, and every file beneath them
        would be reported unreferenced.
        """
        assert self._rel(f"{directory}/script.py") == directory


class TestWindowsModulePaths:
    """Import targets are compared as ``normcase``d path strings.

    The comparison has to be the case-insensitive one ``Path`` equality
    would have made on Windows, where ``import MyModule`` really does
    reach ``mymodule.py``. Folding only the base directory left every
    authored component unfolded, so the bundled module was reported
    unreferenced on exactly the platform the folding exists for.
    """

    @staticmethod
    def _marked(parts, names, on_disk):
        import os
        from unittest import mock

        from skillsaw.rules.builtin.agentskills.unreferenced_files import (
            AgentSkillUnreferencedFilesRule,
        )

        targets: set = set()
        # normcase is the identity on POSIX, so the Windows behaviour has
        # to be simulated to be tested at all.
        with mock.patch.object(os.path, "normcase", str.lower):
            AgentSkillUnreferencedFilesRule._mark_module(
                os.path.normcase("/skill"), list(parts), list(names), set(on_disk), targets
            )
        return targets

    def test_a_mixed_case_import_reaches_the_lowercased_module(self):
        assert self._marked(["MyModule"], [], {"/skill/mymodule.py"}) == {"/skill/mymodule.py"}

    def test_a_mixed_case_from_import_reaches_its_submodule(self):
        assert self._marked(["Pkg"], ["Helper"], {"/skill/pkg/helper.py"}) == {
            "/skill/pkg/helper.py"
        }

    def test_a_mixed_case_package_marks_its_init(self):
        assert self._marked(["Pkg", "Sub"], [], {"/skill/pkg/__init__.py"}) == {
            "/skill/pkg/__init__.py"
        }
