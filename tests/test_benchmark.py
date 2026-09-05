"""
Smoke tests for the benchmark harness in benchmarks/.

These don't assert on absolute timings (machine-dependent) — they verify
the harness runs end-to-end, produces well-formed results, and that
baseline comparison flags regressions correctly.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmarks"))

import bench
import genrepo


@pytest.fixture(scope="module")
def tiny_repo(tmp_path_factory):
    repo = tmp_path_factory.mktemp("bench") / "tiny"
    counts = genrepo.generate_repo(repo, "tiny")
    assert counts["files"] > 0
    return repo


class TestGenRepo:
    def test_deterministic(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        genrepo.generate_repo(a, "tiny")
        genrepo.generate_repo(b, "tiny")
        files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
        files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
        assert files_a == files_b
        for rel in files_a:
            assert (a / rel).read_bytes() == (b / rel).read_bytes()

    def test_scales_defined(self):
        assert set(genrepo.SCALES) >= {"tiny", "small", "medium", "large"}


class TestRunBenchmark:
    def test_result_structure(self, tiny_repo):
        result = bench.run_benchmark(tiny_repo, repeats=1)
        assert set(result["phases"]) == set(bench.PHASES)
        for stats in result["phases"].values():
            assert 0 <= stats["min"] <= stats["mean"] <= stats["max"]
        assert result["meta"]["lint_tree_nodes"] > 0
        assert result["rules"], "expected per-rule timings"
        # total covers all sub-phases
        subtotal = sum(result["phases"][p]["min"] for p in bench.PHASES if p != "total")
        assert result["phases"]["total"]["min"] >= subtotal * 0.9

    def test_format_report(self, tiny_repo):
        result = bench.run_benchmark(tiny_repo, repeats=1)
        report = bench.format_report(result)
        assert "rules_run" in report
        assert "Slowest rules" in report


class TestCompare:
    def _result(self, total_min):
        return {
            "meta": {},
            "phases": {"total": {"min": total_min, "mean": total_min, "max": total_min}},
        }

    def test_no_regression(self):
        assert bench.compare(self._result(1.0), self._result(1.0)) == []

    def test_improvement_passes(self):
        assert bench.compare(self._result(0.5), self._result(1.0)) == []

    def test_regression_detected(self):
        regressions = bench.compare(self._result(2.0), self._result(1.0), threshold_pct=25)
        assert len(regressions) == 1
        assert "total" in regressions[0]

    def test_within_threshold_passes(self):
        assert bench.compare(self._result(1.1), self._result(1.0), threshold_pct=25) == []

    def test_small_absolute_delta_ignored(self):
        # +100% but only +1ms — below the 5ms noise floor
        assert bench.compare(self._result(0.002), self._result(0.001), threshold_pct=25) == []

    def test_missing_phase_in_baseline_ignored(self):
        baseline = {"meta": {}, "phases": {}}
        assert bench.compare(self._result(2.0), baseline) == []


class TestCli:
    def test_repeats_must_be_positive(self, tiny_repo):
        for bad in ("0", "-1"):
            with pytest.raises(SystemExit):
                bench.main(["--repo", str(tiny_repo), "--repeats", bad])

    def test_main_runs_and_writes_json(self, tiny_repo, tmp_path):
        out = tmp_path / "result.json"
        rc = bench.main(["--repo", str(tiny_repo), "--repeats", "1", "--json", str(out)])
        assert rc == 0
        result = json.loads(out.read_text())
        assert "phases" in result

    def test_save_and_compare_roundtrip(self, tiny_repo, tmp_path):
        baseline = tmp_path / "baseline.json"
        rc = bench.main(["--repo", str(tiny_repo), "--repeats", "1", "--save", str(baseline)])
        assert rc == 0
        assert baseline.exists()
        # Comparing against own baseline with a generous threshold passes
        rc = bench.main(
            [
                "--repo",
                str(tiny_repo),
                "--repeats",
                "1",
                "--compare",
                str(baseline),
                "--threshold",
                "10000",
            ]
        )
        assert rc == 0


@pytest.mark.parametrize("gc_enabled", [True, False])
def test_benchmark_uses_production_gc_policy_and_results(tiny_repo, monkeypatch, gc_enabled):
    import gc

    from skillsaw.context import RepositoryContext
    from skillsaw.linter import Linter
    import skillsaw.lint_tree as tree_module
    from skillsaw.rules.builtin.agentskills import AgentSkillDescriptionRule
    from skillsaw.config import LinterConfig

    previous = gc.isenabled()
    observed = []
    tree_observed = []
    findings = []
    original_check = AgentSkillDescriptionRule.check
    original_run = Linter.run
    original_build = tree_module.build_lint_tree_safe

    def build(context):
        tree_observed.append(gc.isenabled())
        return original_build(context)

    def check(rule, context):
        observed.append(gc.isenabled())
        return original_check(rule, context)

    def run(linter, *args, **kwargs):
        result = original_run(linter, *args, **kwargs)
        findings.append([(v.rule_id, v.file_path, v.file_line, v.message) for v in result])
        return result

    monkeypatch.setattr(AgentSkillDescriptionRule, "check", check)
    monkeypatch.setattr(tree_module, "build_lint_tree_safe", build)
    monkeypatch.setattr(Linter, "run", run)
    try:
        gc.enable() if gc_enabled else gc.disable()
        _, per_rule, count, _ = bench._fresh_lint(tiny_repo)
        assert gc.isenabled() == gc_enabled
        Linter(RepositoryContext(tiny_repo), LinterConfig.default()).run()
        assert gc.isenabled() == gc_enabled
        assert observed == [False, False]
        assert tree_observed == [False, False]
        assert "agentskill-description" in per_rule
        assert len(findings) == 2 and findings[0] == findings[1]
        assert count == len(findings[0])
    finally:
        gc.enable() if previous else gc.disable()


def test_benchmark_rejects_caught_rule_failures_and_restores_gc(tiny_repo, monkeypatch):
    import gc

    from skillsaw.rules.builtin.agentskills import AgentSkillDescriptionRule

    def broken(rule, context):
        raise RuntimeError("benchmark canary failure")

    monkeypatch.setattr(AgentSkillDescriptionRule, "check", broken)
    previous = gc.isenabled()
    with pytest.raises(RuntimeError, match="Benchmark lint failed:.*benchmark canary failure"):
        bench._fresh_lint(tiny_repo)
    assert gc.isenabled() == previous
