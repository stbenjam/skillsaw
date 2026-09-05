# Real-corpus performance audit — 2026-09-05

These changes reduce peak memory on the tested repositories containing many Markdown
files. Ai-helpers and Awesome Copilot also show modest, consistent time savings.
Tons of Skills has mixed timing pairs, so its lower median is not evidence of
a consistent speedup. Gh-aw and Superpowers are essentially unchanged.

## Measurements

Four fresh-process pairs, balanced AB/BA, after one warmup per source. Both
sources use the same Python 3.14.5 interpreter and dependencies on Linux
aarch64, with a warm OS cache. Wall time is GNU time's child measurement;
peak RSS is measured separately for each process. Values are medians, with
wall-time ranges in parentheses. These are observations on one host, not
cross-platform guarantees or statistical significance claims.

| Repository | Main wall seconds | Branch wall seconds | Main peak MiB | Branch peak MiB |
| --- | ---: | ---: | ---: | ---: |
| Tons of Skills | 21.52 (20.25–22.72) | 20.47 (20.36–20.81) | 1209.90 | 813.34 |
| ai-helpers | 2.26 (2.21–2.50) | 2.10 (2.09–2.11) | 185.57 | 150.55 |
| Awesome Copilot | 6.28 (6.26–6.28) | 6.10 (6.09–6.11) | 438.94 | 289.39 |
| gh-aw | 11.99 (11.94–12.13) | 11.98 (11.97–11.98) | 248.37 | 247.42 |
| Superpowers | 0.30 (0.29–0.36) | 0.30 (0.29–0.31) | 48.14 | 47.80 |

Peak memory falls 32.8%, 18.9%, and 34.1% on the first three repositories.
Ai-helpers improves about 7% in wall time; Awesome Copilot improves about 3%.
Both improve in all four pairs and in user+system CPU time. The individual
wall, CPU and RSS samples are in [the measurement data](2026-09-05-real-corpus.json).

## Changes and correctness

- Group verbatim spans by inline token, avoiding redundant source maps.
- Stop skill reachability when every bundled file has been referenced.
- After extracting inline results, release document-local references to
  consumed children and unused structural tokens. Shallow copies preserve
  the shared parser cache for other documents and their file coordinates.

The retained token types cover every current Markdown facade query. Adding a
new accessor may require extending `_POST_WALK_TOKEN_TYPES`. Token order,
content, maps and nesting levels remain available for subsequent queries.

All 50 CLI reports (warmups included), ordered findings, stderr and exit codes
matched their baseline after removing only `stats.duration_seconds`. Separate
untimed captures also matched complete returned diagnostics, including INFO,
fix data, fingerprint discriminators and consolidation, plus ordered lint-tree nodes,
ownership, provenance, policy flags and effective rules/settings on all five
repositories. Tons of Skills discovers 3,538 skills, 437 plugins and 56 rules;
its 5,829 diagnostics and 48,287 tree nodes are unchanged. Diagnostic counts
are untriaged; they do not measure false-positive rates.

Validation: 9,179 tests passed; `make lint`, `make update` and self-lint passed;
normal configured ai-helpers lint exited 0. Five new tests protect removed work,
shared-cache isolation, distinct file mappings, lazy queries and transitive
reachability. The existing phase benchmark's baseline-save/compare gate also
passed on real ai-helpers. Its in-process cache behavior differs from the
fresh CLI and is supplementary evidence only.

## Reproduction and scope

The baseline is main `d35234c459ec271c9540a9fb5a59f72cc77d1e6e`; the measured
runtime candidate is `2139de08974127b0271fb1176900887cea43d601`. Corpus commits,
key dependency versions, configuration digest and raw samples are in the linked
JSON file. Both sources use one saved `LinterConfig.default()` configuration
from the baseline. Corpus-specific configuration and lint baselines are
intentionally excluded from the performance comparison; the ai-helpers
compatibility smoke separately uses its normal configuration and baseline.

For each pinned corpus, select the source through `PYTHONPATH` and run the
actual CLI using the same virtualenv, frozen defaults and output sink:

```sh
TMPDIR="$HOME/tmp" PYTHONHASHSEED=0 PYTHONNOUSERSITE=1 \
PYTHONSAFEPATH=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$source/src" \
/usr/bin/time -f '%e wall seconds; %U user; %S system; %M peak KiB' \
"$venv/bin/python3" -m skillsaw lint "$corpus" \
  --config "$frozen_defaults" --no-custom-rules --no-plugins --no-baseline \
  --format json > "$report"
```

Keep sources and corpus inputs frozen; verify the imported source, retain each
report and compare it before accepting a timing. Expected lint exit 1 reflects
diagnostics, not incomplete execution. Refuse infrastructure failures. Run
one warmup per source and alternate four timed pairs without competing heavy
work. The audit used no synthetic corpus and executed no corpus extensions.

The largest rule attribution was mostly shared Markdown parsing, paid by its
first consumer. Additional path caches and traversal machinery had small
measured ceilings and were not added. Full parsing remains the principal
cost. The shared AST cache still retains up to 128 entries; this change does
not establish a per-file memory budget or promise gains on a few very large
documents. The gh-aw control showed no material improvement.
