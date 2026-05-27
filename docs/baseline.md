# Baseline

When adopting skillsaw on an existing project, you may have many
pre-existing violations. The **baseline** feature lets you snapshot
current violations so that `skillsaw lint` only reports *new* ones —
existing violations are accepted and won't fail CI.

## Creating a Baseline

Generate a `.skillsaw-baseline.json` from the current violations:

```bash
skillsaw baseline
```

Write to a custom path:

```bash
skillsaw baseline -o my-baseline.json
```

The baseline file should be committed to your repository so that CI and
other developers share the same accepted set of violations.

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

## Ignoring the Baseline

Run lint without baseline filtering:

```bash
skillsaw lint --no-baseline
```

## Stale Entries

When you fix a baselined violation, its baseline entry becomes **stale**.
Skillsaw reports stale entries so you know the baseline can be refreshed:

```
Baseline: 3 stale entries (violations resolved since baseline was set)
  Run `skillsaw baseline` to update.
```

Run `skillsaw baseline` again to regenerate the file without the
resolved violations.

## Configuration

You can set a custom baseline path in `.skillsaw.yaml`:

```yaml
baseline: path/to/my-baseline.json
```

When omitted, skillsaw auto-discovers `.skillsaw-baseline.json` by
walking up the directory tree (same behavior as config discovery).

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

# 4. CI now passes — only new violations will fail
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
