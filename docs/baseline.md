# Baseline

When adopting skillsaw on an existing project, you may have many
pre-existing violations. The **baseline** feature lets you snapshot
current violations so that `skillsaw lint` only reports *new* ones —
existing violations are accepted and won't cause failures.

## Creating a Baseline

Generate a `.skillsaw-baseline.json` from the current violations:

```bash
skillsaw baseline
```

The baseline file should be committed to your repository so that all
contributors share the same accepted set of violations.

## How It Works

Once a `.skillsaw-baseline.json` file exists (next to `.skillsaw.yaml` or
in the repo root), `skillsaw lint` automatically loads it and subtracts
matching violations from the output. Only new violations are reported.

Violations are matched by a **content hash** — a fingerprint built from
the rule ID, file path, and the content of the source line (not the line
number). This means the baseline survives line drift: if you add lines
above a baselined violation, the fingerprint still matches because the
content hasn't changed.

If you reformat or rewrite a line, the fingerprint changes and the
violation resurfaces for a fresh look — which is the correct behavior.

## Ratchet Rules

Some rules measure a numeric value (token count, instruction count,
actionability score) rather than flagging a specific line. These rules
use **ratchet** behavior: the baseline records the value at the time it
was created and only suppresses violations that are equal to or *better*
than the baseline. If the value gets worse, the violation is reported.

For example, if `context-budget` records 5,000 tokens at baseline time:

- Shrink the file to 4,800 tokens → **suppressed** (improvement)
- Grow the file to 5,200 tokens → **reported** (regression)
- Get under the limit entirely → violation disappears, baseline entry becomes stale

Rules with ratchet behavior:

| Rule | Metric | Baseline acts as |
|------|--------|-----------------|
| `context-budget` | token count | ceiling (can't increase) |
| `content-instruction-budget` | instruction count | ceiling (can't increase) |
| `content-actionability-score` | actionability score | floor (can't decrease) |

All other rules use fingerprint matching — the violation is suppressed
as long as the source line content hasn't changed.

## Ignoring the Baseline

Run lint without baseline filtering:

```bash
skillsaw lint --no-baseline
```

## Lint Only Your Changes (`--since`)

`--since REF` builds the baseline on the fly from git history — no
committed `.skillsaw-baseline.json`, no setup:

```bash
# Report only violations introduced on your branch
skillsaw lint --since origin/main

# Report only violations introduced by the last commit
skillsaw lint --since HEAD~1
```

### How it works

`--since` resolves the **merge-base** of HEAD and REF (the commit your
work diverged from), checks it out into a temporary git worktree, lints
that snapshot with the same configuration, and uses the result as an
ephemeral baseline. The temporary worktree is always removed afterwards.

Because the ephemeral baseline uses the same content-hash fingerprints
as a committed baseline, everything above applies:

- **Drift immunity** — pre-existing violations stay suppressed even when
  your change inserts or removes lines around them.
- **Ratchet composition** — value-carrying rules (`context-budget`,
  `content-instruction-budget`, `content-actionability-score`) re-fire
  only when your change makes the tracked value worse. Growing a
  SKILL.md past its merge-base token count reports the regression;
  shrinking it stays quiet.
- Fixed violations are reported as
  `Baseline: N violation(s) fixed since REF`.

Merge-base semantics mean commits that landed on REF after you branched
are not counted against you — only your own changes are compared.

The rule configuration (`.skillsaw.yaml`, `--rule`/`--skip-rule`,
`--no-custom-rules`, `--no-plugins`) is deliberately taken from the
*current* working tree for both lints: `--since` measures how the
repository changed, not how the rule configuration changed.

`--since` takes precedence over a committed `.skillsaw-baseline.json`
and cannot be combined with `--no-baseline`.

### Limitations

- **Renames resurface old violations** — fingerprints include the
  relative file path, so violations in a renamed file no longer match
  their merge-base entries and are reported again.
- **Roughly doubles lint time** — the merge-base snapshot is linted in
  addition to the working tree.
- **Requires git history** — the merge-base commit must be reachable.
  In shallow CI clones, fetch history first (e.g. `fetch-depth: 0` with
  `actions/checkout`, or `git fetch --unshallow`); skillsaw reports a
  precise error when it cannot resolve the merge-base.

## Stale Entries

When you fix a baselined violation, its baseline entry becomes **stale**.
Skillsaw reports stale entries so you know the baseline can be refreshed:

```
Baseline: 3 stale entries (violations resolved since baseline was set)
  Run `skillsaw baseline` to update.
```

Run `skillsaw baseline` again to regenerate the file without the
resolved violations.

## Baseline and Fix

The `skillsaw fix` command operates on all violations regardless of the
baseline. The baseline only affects `lint` reporting and exit codes — if
you explicitly ask to fix, everything is eligible.

## Workflow Example

A typical adoption workflow:

```bash
# 1. Set up skillsaw
skillsaw init

# 2. See what violations exist
skillsaw lint

# 3. Accept them as the baseline
skillsaw baseline

# 4. Lint now passes — only new violations will fail
skillsaw lint  # exit 0

# 5. Over time, fix violations and re-baseline
skillsaw baseline  # updates the file with fewer entries
```

## Baseline File Format

The `.skillsaw-baseline.json` file is a JSON document:

```json
{
  "version": "1",
  "generated_by": "skillsaw 0.10.1",
  "generated_at": "2025-05-27T12:00:00+00:00",
  "violations": [
    {
      "fingerprint": "a1b2c3d4e5f6g7h8",
      "rule_id": "content-weak-language",
      "file_path": "CLAUDE.md",
      "line": 42,
      "message": "Weak language: 'try to'",
      "severity": "warning"
    }
  ]
}
```

The `fingerprint` field is the content hash used for matching. The
`line` field is stored for human readability but is not part of the
match key — violations are matched by content, not position.
