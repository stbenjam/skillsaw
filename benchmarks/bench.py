"""Benchmark harness for skillsaw linting performance.

Measures wall time for each linting phase (repository discovery, rule
loading, lint tree construction, rule execution) plus per-rule timing,
and supports saving/comparing JSON baselines to catch regressions.

Usage:
    .venv/bin/python3 benchmarks/bench.py --scale medium
    .venv/bin/python3 benchmarks/bench.py --repo /path/to/repo
    .venv/bin/python3 benchmarks/bench.py --scale medium --save .benchmarks/baseline.json
    .venv/bin/python3 benchmarks/bench.py --scale medium --compare .benchmarks/baseline.json
    .venv/bin/python3 benchmarks/bench.py --scale medium --profile

Baselines record wall time and are only meaningful when compared on the
same machine.  The comparison uses the minimum across repeats (least
noisy estimator) with a configurable tolerance.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import platform
import pstats
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from genrepo import SCALES, generate_repo

PHASES = ("context", "linter_init", "lint_tree", "rules_run", "total")


def _fresh_lint(repo_path: Path):
    """Run one full lint with cold caches, timing each phase.

    Returns (phase_timings, per_rule_timings, violation_count, node_count).
    """
    from skillsaw.config import LinterConfig
    from skillsaw.context import RepositoryContext
    from skillsaw.linter import Linter
    from skillsaw.rules.builtin.utils import invalidate_read_caches

    invalidate_read_caches()
    phases: Dict[str, float] = {}

    t0 = time.perf_counter()
    context = RepositoryContext(repo_path)
    t1 = time.perf_counter()
    phases["context"] = t1 - t0

    config = LinterConfig.default()
    linter = Linter(context, config)
    t2 = time.perf_counter()
    phases["linter_init"] = t2 - t1

    node_count = sum(1 for _ in context.lint_tree.walk())
    t3 = time.perf_counter()
    phases["lint_tree"] = t3 - t2

    # Mirror Linter.run() but attribute time to each rule.  Rule crashes
    # propagate — a baseline recorded through a crashing rule (which takes
    # ~0ms) would corrupt every later comparison.
    per_rule: Dict[str, float] = {}
    violations = linter._validate_config()
    for rule in linter.rules:
        r0 = time.perf_counter()
        rule_violations = rule.check(context)
        per_rule[rule.rule_id] = time.perf_counter() - r0
        violations.extend(rule_violations)
    violations = linter._filter_violations(violations)
    t4 = time.perf_counter()
    phases["rules_run"] = t4 - t3
    phases["total"] = t4 - t0

    return phases, per_rule, len(violations), node_count


def run_benchmark(repo_path: Path, repeats: int = 3) -> dict:
    """Benchmark linting *repo_path*, returning a JSON-serializable result.

    Runs one untimed warmup iteration (imports, bytecode, OS file cache)
    followed by *repeats* timed iterations with cold skillsaw caches.
    """
    _fresh_lint(repo_path)  # warmup

    phase_samples: Dict[str, List[float]] = {p: [] for p in PHASES}
    rule_samples: Dict[str, List[float]] = {}
    violation_count = node_count = 0

    for _ in range(repeats):
        phases, per_rule, violation_count, node_count = _fresh_lint(repo_path)
        for p in PHASES:
            phase_samples[p].append(phases[p])
        for rule_id, dt in per_rule.items():
            rule_samples.setdefault(rule_id, []).append(dt)

    def stats(samples: List[float]) -> dict:
        return {
            "min": min(samples),
            "mean": statistics.fmean(samples),
            "max": max(samples),
        }

    return {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "repo": str(repo_path),
            "repeats": repeats,
            "violations": violation_count,
            "lint_tree_nodes": node_count,
        },
        "phases": {p: stats(s) for p, s in phase_samples.items()},
        "rules": {
            rule_id: stats(s)
            for rule_id, s in sorted(
                rule_samples.items(), key=lambda kv: -min(kv[1])
            )
        },
    }


def compare(current: dict, baseline: dict, threshold_pct: float = 25.0) -> List[str]:
    """Compare *current* against *baseline*; return regression descriptions.

    A phase regresses when its min time exceeds the baseline min by more
    than *threshold_pct* percent (and by at least 5ms, to ignore noise on
    sub-millisecond phases).
    """
    regressions = []
    for phase, cur in current["phases"].items():
        base = baseline.get("phases", {}).get(phase)
        if not base:
            continue
        delta = cur["min"] - base["min"]
        if base["min"] > 0 and delta > 0.005:
            pct = 100.0 * delta / base["min"]
            if pct > threshold_pct:
                regressions.append(
                    f"{phase}: {base['min'] * 1000:.1f}ms -> {cur['min'] * 1000:.1f}ms "
                    f"(+{pct:.0f}%, threshold {threshold_pct:.0f}%)"
                )
    return regressions


def profile_lint(repo_path: Path, out_path: Optional[Path] = None, top: int = 25) -> str:
    """Profile one full cold lint with cProfile; return a formatted report."""
    _fresh_lint(repo_path)  # warmup so imports don't dominate the profile

    profiler = cProfile.Profile()
    profiler.enable()
    _fresh_lint(repo_path)
    profiler.disable()

    if out_path:
        profiler.dump_stats(out_path)

    buf = io.StringIO()
    ps = pstats.Stats(profiler, stream=buf)
    ps.strip_dirs()
    buf.write("== Top functions by cumulative time ==\n")
    ps.sort_stats("cumulative").print_stats(top)
    buf.write("\n== Top functions by internal time ==\n")
    ps.sort_stats("tottime").print_stats(top)
    return buf.getvalue()


def format_report(result: dict, top_rules: int = 15) -> str:
    lines = []
    meta = result["meta"]
    lines.append(
        f"Benchmark: {meta['repo']}  "
        f"(nodes={meta['lint_tree_nodes']}, violations={meta['violations']}, "
        f"repeats={meta['repeats']})"
    )
    lines.append("")
    lines.append(f"{'phase':<14} {'min':>10} {'mean':>10} {'max':>10}")
    for phase in PHASES:
        s = result["phases"][phase]
        lines.append(
            f"{phase:<14} {s['min'] * 1000:>8.1f}ms {s['mean'] * 1000:>8.1f}ms "
            f"{s['max'] * 1000:>8.1f}ms"
        )
    lines.append("")
    lines.append(f"Slowest rules (top {top_rules}, by min time):")
    lines.append(f"{'rule':<40} {'min':>10} {'mean':>10}")
    for rule_id, s in list(result["rules"].items())[:top_rules]:
        lines.append(
            f"{rule_id:<40} {s['min'] * 1000:>8.1f}ms {s['mean'] * 1000:>8.1f}ms"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark skillsaw linting")
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--scale",
        choices=sorted(SCALES),
        default="medium",
        help="Generate a synthetic repo at this scale (default: medium)",
    )
    target.add_argument("--repo", type=Path, help="Benchmark an existing repository")
    parser.add_argument("--repeats", type=int, default=3, help="Timed iterations")
    parser.add_argument("--json", type=Path, help="Write results JSON to this path")
    parser.add_argument("--save", type=Path, help="Save results as baseline JSON")
    parser.add_argument(
        "--compare", type=Path, help="Compare against a baseline JSON; exit 1 on regression"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=25.0,
        help="Regression threshold in percent (default: 25)",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Run under cProfile and print hotspots instead of timing repeats",
    )
    parser.add_argument(
        "--profile-out", type=Path, help="Also dump raw pstats data to this path"
    )
    args = parser.parse_args(argv)

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    # Validate the baseline before the (slow) benchmark run so a missing file
    # fails fast with guidance instead of crashing after all the work.
    if args.compare and not args.compare.exists():
        parser.error(
            f"baseline not found: {args.compare}\n"
            "save one first on a clean tree: make benchmark-save"
        )

    with tempfile.TemporaryDirectory(prefix="skillsaw-bench-") as tmp:
        if args.repo:
            repo_path = args.repo.resolve()
        else:
            repo_path = Path(tmp) / args.scale
            counts = generate_repo(repo_path, args.scale)
            print(
                f"Generated {args.scale} repo: {counts['files']} files, "
                f"{counts['plugins']} plugins, {counts['skills']} skills",
                file=sys.stderr,
            )

        if args.profile:
            print(profile_lint(repo_path, args.profile_out))
            return 0

        result = run_benchmark(repo_path, repeats=args.repeats)

    print(format_report(result))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline saved to {args.save}")

    if args.compare:
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        regressions = compare(result, baseline, args.threshold)
        print(f"\nCompared against {args.compare} "
              f"(saved {baseline.get('meta', {}).get('timestamp', 'unknown')})")
        if regressions:
            print("PERFORMANCE REGRESSIONS DETECTED:")
            for r in regressions:
                print(f"  - {r}")
            return 1
        print("No regressions detected.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
