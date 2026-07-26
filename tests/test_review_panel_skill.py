"""Regression guards for the review-panel skill.

The panel is a prompt, not code, so its failure modes are textual: an
instruction that drifts, a roster entry that loses its scope file, a
generated copy that falls out of sync. Those are invisible to the rest of
the suite — ``make lint`` and the generators stay green while the workflow
misbehaves — which is exactly how the headless silent-exit bug shipped.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIRS = [
    REPO_ROOT / d / "skills" / "skillsaw-review-panel" for d in (".apm", ".agents", ".claude")
]
SOURCE = SKILL_DIRS[0]

SPECIALISTS = [
    ("Architecture Reviewer", "architecture.md"),
    ("Python Expert", "python-expert.md"),
    ("Security & Supply Chain Reviewer", "security-supply-chain.md"),
    ("QA Engineer", "qa-engineer.md"),
    ("Technical Writer", "technical-writer.md"),
    ("Ecosystem Reviewer", "ecosystem.md"),
    ("Palimpsest Reviewer", "palimpsest.md"),
]


def skill_md(directory: Path) -> str:
    return (directory / "SKILL.md").read_text(encoding="utf-8")


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


class TestPalimpsestSeverityIsArbitrated:
    """Specialists cannot see each other, so a corroboration condition the
    specialist evaluates itself can never be satisfied — it would always
    self-downgrade, and a corroborated correctness defect would ship as a
    suggestion under an APPROVE."""

    def test_it_reports_a_candidate_rather_than_deciding(self):
        scope = (SOURCE / "references" / "palimpsest.md").read_text(encoding="utf-8")
        assert "BLOCKING CANDIDATE" in scope
        assert "do not downgrade it yourself" in scope

    def test_the_arbiter_settles_candidates(self):
        body = skill_md(SOURCE)
        assert "Settle blocking candidates" in body
        body = " ".join(body.split())
        assert "Leaving it unsettled is" in " ".join(body.split())

    def test_the_reviewer_stays_advisory_by_default(self):
        scope = (SOURCE / "references" / "palimpsest.md").read_text(encoding="utf-8")
        assert "What NOT to flag" in scope


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
