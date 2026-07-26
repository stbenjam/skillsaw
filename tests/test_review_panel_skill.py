"""Regression guards for the review-panel skill.

The panel is a prompt, not code, so its failure modes are textual: an
instruction that drifts, a roster entry that loses its scope file, a
generated copy that falls out of sync. Those are invisible to the rest of
the suite — ``make lint`` and the generators stay green while the workflow
misbehaves — which is exactly how the headless silent-exit bug shipped.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIRS = [
    REPO_ROOT / d / "skills" / "skillsaw-review-panel" for d in (".apm", ".agents", ".claude")
]
SOURCE = SKILL_DIRS[0]
SCOPE = SOURCE / "references" / "slopinator.md"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "slopinator-review-residue"

SPECIALISTS = [
    ("Architecture Reviewer", "architecture.md"),
    ("Python Expert", "python-expert.md"),
    ("Security & Supply Chain Reviewer", "security-supply-chain.md"),
    ("QA Engineer", "qa-engineer.md"),
    ("Technical Writer", "technical-writer.md"),
    ("Ecosystem Reviewer", "ecosystem.md"),
    ("Slopinator Reviewer", "slopinator.md"),
]


def skill_md(directory: Path) -> str:
    return (directory / "SKILL.md").read_text(encoding="utf-8")


def scope_md() -> str:
    return SCOPE.read_text(encoding="utf-8")


def bullet_terms(heading: str) -> List[str]:
    """Bold lead-in terms of the bullets under ``heading`` in the scope file.

    Used to detect drift: the scope file is the source of truth for what the
    reviewer looks for, so a pattern added there must gain a fixture example.
    """
    body = scope_md()
    start = body.index(heading) + len(heading)
    rest = body[start:]
    end = re.search(r"^#{2,4} ", rest, re.MULTILINE)
    section = rest[: end.start()] if end else rest
    return [m.group(1) for m in re.finditer(r"^- \*\*(.+?)\*\*", section, re.MULTILINE)]


def fixture_text(relative: str) -> str:
    return (FIXTURE / relative).read_text(encoding="utf-8")


CATALOG = "src/catalog.py"
OVERVIEW = "docs/overview.md"

# Scope-file pattern -> (fixture file, a marker that instantiates it).
CODE_PATTERNS: Dict[str, Tuple[str, str]] = {
    "Phantom bugs": (CATALOG, "Without this a Codex catalog fell through"),
    "Round-scoped measurements": (CATALOG, "99.2% of extract_docs runtime"),
    "Fix-sequence narration": (CATALOG, "The direct probes were fixed"),
    "Round-numbered test organization": (
        "tests/catalog_test.py",
        "Review follow-ups, round three",
    ),
    "Change announcements": (CATALOG, "# now also handles nested catalogs"),
    "Prose restatements of the code": (CATALOG, "# increment the counter"),
    "Defensive over-commenting": (CATALOG, "# close the file"),
    "Signature-echo docstrings": (CATALOG, "follow_links: whether to follow links."),
    "Conversational filler": (CATALOG, "# note that the caller"),
    "Changelog narration in code": (CATALOG, "v1.2 — added multi-page support"),
}

PROSE_PATTERNS: Dict[str, Tuple[str, str]] = {
    "AI vocabulary tells": (OVERVIEW, "intricate tapestry"),
    "Copula avoidance": (OVERVIEW, "serves as the entry point"),
    "Rule-of-three padding": (OVERVIEW, "and **maintainable**"),
    "Negative parallelism": (OVERVIEW, "It's not just a parser, it's"),
    "Signposting": (OVERVIEW, "Let's dive into"),
    "Sycophancy": (OVERVIEW, "You're absolutely right"),
    "Hedging and filler": (OVERVIEW, "could potentially possibly"),
}

SHAPE_PATTERNS: Dict[str, Tuple[str, str]] = {
    "Em dash and boldface abuse": (OVERVIEW, "a **discovery layer**"),
    "Title Case headings": (OVERVIEW, "## Understanding The Catalog Landscape"),
    "Manufactured punchlines and staccato drama": (OVERVIEW, "No retry. No mercy."),
    "Generic conclusions": (OVERVIEW, "The future looks bright"),
    "Chatbot artifacts": (OVERVIEW, "I hope this helps!"),
}

# Constructs the reviewer must leave alone.
CLEAN_CASES: Dict[str, Tuple[str, str]] = {
    'Long "why" comments that earn their length.': ("src/renderer.py", "jinja2 issue 1842"),
    "Project house style.": ("docs/reference.md", "House style for this project"),
    "Domain vocabulary.": ("docs/reference.md", "terms of art, not inflated diction"),
    "An em dash doing ordinary work.": ("docs/reference.md", "One of them is not a tell."),
    "Version-scoped documents.": ("CHANGELOG.md", "Narrating change is the whole job here"),
    "Test names that read verbosely": (
        "tests/catalog_test.py",
        "test_a_nested_catalog_with_a_symlinked_parent_is_not_traversed_twice",
    ),
}

# Two "what not to flag" rules describe a property of the review situation,
# not of any file, so no static fixture can carry an example: one needs a PR
# thread showing the request, the other needs a diff to tell moved text from
# new text. They are declared here so the coverage check below stays honest
# rather than being silently narrowed.
UNREPRESENTABLE_CLEAN_CASES = {
    "Comments a reviewer explicitly requested.",
    "Existing text the diff merely moves.",
}

CLEAN_FILES = ["src/renderer.py", "docs/reference.md", "CHANGELOG.md"]


class TestDispatchIsAwaited:
    """A background dispatch ends the turn, which ends a headless CI job.

    The workflow then exits green having posted no verdict — indistinguishable
    from a clean review unless someone reads the execution artifact.
    """

    def test_parallel_dispatch_is_synchronous(self):
        body = skill_md(SOURCE)
        assert "`run_in_background: false`" in body

    def test_background_dispatch_is_not_instructed(self):
        """`true` may appear only in the prohibition explaining why not."""
        flat = " ".join(skill_md(SOURCE).split())
        occurrences = flat.count("run_in_background: true")
        assert occurrences == 1, f"expected one mention, found {occurrences}"
        assert "Do **not** use `run_in_background: true`" in flat

    def test_the_run_may_not_end_before_the_verdict(self):
        assert "Never end the run here" in skill_md(SOURCE)


class TestRoster:
    @pytest.mark.parametrize("name,reference", SPECIALISTS)
    def test_each_specialist_is_listed_with_its_scope_file(self, name, reference):
        body = skill_md(SOURCE)
        assert name in body, f"{name} missing from the roster"
        assert f"references/{reference}" in body
        assert (SOURCE / "references" / reference).is_file()

    def test_the_declared_count_matches_the_roster(self):
        body = skill_md(SOURCE)
        count = len(SPECIALISTS)
        assert f"all {count} specialist sub-agents" in body
        assert f"Dispatches {count} specialist reviewers" in body
        serial = (SOURCE / "references" / "serial-mode.md").read_text(encoding="utf-8")
        assert f"Run all {count} specialists" in serial

    def test_every_specialist_has_a_quality_gate(self):
        body = skill_md(SOURCE)
        for name, _ in SPECIALISTS:
            short = name.replace(" Reviewer", "").replace(" Engineer", "")
            assert f"- [ ] {name}" in body or short in body


class TestSlopinatorSeverityIsArbitrated:
    """Specialists cannot see each other, so a corroboration condition the
    specialist evaluates itself can never be satisfied — it would always
    self-downgrade, and a corroborated correctness defect would ship as a
    suggestion under an APPROVE."""

    def test_it_reports_a_candidate_rather_than_deciding(self):
        scope = (SOURCE / "references" / "slopinator.md").read_text(encoding="utf-8")
        assert "BLOCKING CANDIDATE" in scope
        assert "do not downgrade it yourself" in scope

    def test_the_arbiter_settles_candidates(self):
        body = skill_md(SOURCE)
        assert "Settle blocking candidates" in body
        body = " ".join(body.split())
        assert "Leaving it unsettled is" in " ".join(body.split())

    def test_the_reviewer_stays_advisory_by_default(self):
        scope = (SOURCE / "references" / "slopinator.md").read_text(encoding="utf-8")
        assert "What NOT to flag" in scope


class TestCorroborationContractIsConsistent:
    """Three places state when a Slopinator finding may block: the shared
    severity list, the scope file, and the arbiter's settle step. If they
    disagree, the specialist and the arbiter apply different rules and the
    label means whatever the reader last happened to read.
    """

    def test_the_shared_severity_list_defines_corroboration(self):
        body = " ".join(skill_md(SOURCE).split())
        assert (
            "Corroboration means another specialist independently reports "
            "the same underlying defect" in body
        )
        assert "not merely a finding in the same file" in body

    def test_the_scope_file_uses_the_same_definition(self):
        scope = " ".join(scope_md().split())
        assert "any other specialist independently reports the same underlying defect" in scope
        assert "not merely a finding in the same file" in scope

    def test_the_arbiter_step_uses_the_same_definition(self):
        body = " ".join(skill_md(SOURCE).split())
        assert (
            "Promote to `BLOCKING` when any other specialist independently "
            "reported the same underlying defect" in body
        )

    def test_corroboration_is_not_narrowed_to_named_specialists_or_to_a_file(self):
        """Earlier drafts gated on Architecture or the Technical Writer in one
        place and on touching the same file in another. Both are narrower than
        the rule the other two places state."""
        joined = " ".join((skill_md(SOURCE) + scope_md()).split())
        for phrase in (
            "Architecture or the Technical Writer",
            "Architecture or Technical Writer",
            "reaches the same file",
            "reached the same claim",
        ):
            assert phrase not in joined, f"narrower corroboration rule survives: {phrase}"


class TestFindingsFormatCarriesEverySeverity:
    """The shared findings format is the whole contract an isolated sub-agent
    receives. A label missing from it cannot be emitted, so the arbitration
    step that consumes it would never fire and the specialist would fall back
    to deciding a severity it cannot judge alone.
    """

    def test_blocking_candidate_is_in_the_shared_severity_list(self):
        body = skill_md(SOURCE)
        assert "`BLOCKING` | `BLOCKING CANDIDATE` | `SUGGESTION` | `NOTE`" in body

    def test_the_label_is_scoped_to_slopinator_and_promoted_only_by_the_arbiter(self):
        body = " ".join(skill_md(SOURCE).split())
        assert "**Slopinator Reviewer only**" in body
        assert "no other specialist uses it" in body
        assert "Only the arbiter promotes it" in body


class TestDispatchGateDoesNotStallOnFailure:
    """The gate is "don't read results that are still arriving", not "every
    specialist must succeed" — Step 4 explicitly records an unrecoverable
    specialist and carries on."""

    def test_the_gate_is_about_arrival_not_success(self):
        body = " ".join(skill_md(SOURCE).split())
        assert "Do not start Step 4 while results are still arriving" in body
        assert "a specialist that errors is handled there, not waited on" in body

    def test_a_failed_specialist_still_yields_a_verdict(self):
        body = " ".join(skill_md(SOURCE).split())
        assert "If the retry also fails, record the failure and proceed." in body
        assert "post the verdict anyway, naming which failed" in body


class TestSlopinatorFixture:
    """A small repo carrying what the reviewer is meant to catch, beside what
    it must leave alone.

    These assertions pin the fixture to the scope file so the two cannot
    drift: a pattern added to one without the other fails here. They do not
    assert that the reviewer *catches* anything. The panel is a prompt
    executed by an LLM, so recall and precision need a model in the loop and
    cannot be checked in a unit suite — point a live panel run at the fixture
    instead. See ``tests/fixtures/slopinator-review-residue/README.md``.
    """

    ALL_PATTERNS = dict(CODE_PATTERNS, **PROSE_PATTERNS, **SHAPE_PATTERNS)

    @pytest.mark.parametrize("pattern,location", sorted(ALL_PATTERNS.items()))
    def test_each_pattern_has_a_fixture_instance(self, pattern, location):
        relative, marker = location
        assert marker in fixture_text(relative), f"{pattern}: no instance in {relative}"

    @pytest.mark.parametrize(
        "heading,mapping",
        [
            ("### What to flag in code", CODE_PATTERNS),
            ("### Tells to flag in prose", PROSE_PATTERNS),
            ("### Formatting and shape tells", SHAPE_PATTERNS),
        ],
    )
    def test_the_fixture_covers_every_pattern_the_scope_file_names(self, heading, mapping):
        assert set(bullet_terms(heading)) == set(mapping)

    @pytest.mark.parametrize("case,location", sorted(CLEAN_CASES.items()))
    def test_each_false_positive_guard_has_a_fixture_instance(self, case, location):
        relative, marker = location
        assert marker in fixture_text(relative), f"{case}: no instance in {relative}"

    def test_every_false_positive_guard_is_covered_or_declared_unrepresentable(self):
        declared = set(bullet_terms("## What NOT to flag"))
        assert declared == set(CLEAN_CASES) | UNREPRESENTABLE_CLEAN_CASES

    @pytest.mark.parametrize("relative", CLEAN_FILES)
    def test_the_clean_files_carry_no_residue(self, relative):
        body = fixture_text(relative)
        for pattern, (_, marker) in self.ALL_PATTERNS.items():
            assert marker not in body, f"{relative} contains the {pattern} marker"


class TestGeneratedCopiesAreInSync:
    """`.apm/` is the source; `.agents/` and `.claude/` are compiled output.

    A hand-edit to a compiled copy is silently reverted by `make update`.
    """

    @pytest.mark.parametrize("name", ["SKILL.md", "verdict-template.md"])
    def test_top_level_files_match(self, name):
        contents = {(d / name).read_text(encoding="utf-8") for d in SKILL_DIRS}
        assert len(contents) == 1, f"{name} differs between .apm/, .agents/ and .claude/"

    @pytest.mark.parametrize("name,reference", SPECIALISTS)
    def test_reference_files_match(self, name, reference):
        contents = {(d / "references" / reference).read_text(encoding="utf-8") for d in SKILL_DIRS}
        assert len(contents) == 1, f"{reference} differs between copies"


class TestSerialMode:
    """Serial mode lives in a reference file — it is the non-default path,
    and the skill is close enough to its context budget that an always-read
    copy costs more than it earns."""

    def test_the_procedure_is_reachable(self):
        assert "references/serial-mode.md" in skill_md(SOURCE)
        assert (SOURCE / "references" / "serial-mode.md").is_file()

    def test_the_procedure_covers_every_specialist(self):
        body = (SOURCE / "references" / "serial-mode.md").read_text(encoding="utf-8")
        for name, _ in SPECIALISTS:
            short = name.split()[0]
            assert short in body, f"{name} missing from the serial procedure"

    @pytest.mark.parametrize("directory", SKILL_DIRS)
    def test_the_copies_match(self, directory):
        source = (SOURCE / "references" / "serial-mode.md").read_text(encoding="utf-8")
        assert (directory / "references" / "serial-mode.md").read_text(encoding="utf-8") == source


class TestContextBudget:
    def test_the_skill_stays_within_its_warn_limit(self):
        """Adding the seventh specialist pushed this over 3,000 tokens.

        The file is always read, so its size is paid on every invocation.
        """
        body = skill_md(SOURCE)
        assert len(body) // 4 < 3000, f"~{len(body) // 4} tokens, warn limit is 3000"


class TestVerdictTemplate:
    def test_every_specialist_has_a_findings_placeholder(self):
        template = (SOURCE / "verdict-template.md").read_text(encoding="utf-8")
        for name, _ in SPECIALISTS:
            assert name in template, f"{name} has no section in the verdict template"
