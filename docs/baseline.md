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
Fatal infrastructure violations such as `repository-path-error` are not
written to the baseline and can never be suppressed by one. The same
goes for advisory `deprecated-rule` notices: baselining one would
permanently hide the warning that a rule is going away, so they are
never written and never suppressed — remove the deprecated rule from
your config to clear the notice instead.

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

## Stale Entries

When you fix a baselined violation, its baseline entry becomes **stale**.
Skillsaw reports stale entries so you know the baseline can be refreshed:

```
Baseline: 3 stale entries (violations resolved since baseline was set)
  Run `skillsaw baseline` to update.
```

Run `skillsaw baseline` again to regenerate the file without the
resolved violations.

## Upgrading

A skillsaw upgrade can change which files parse, and a file that starts
parsing starts being linted. YAML parsing moved to libyaml (on builds
carrying PyYAML's C extension, which most wheels do), and it accepts
documents PyYAML's own scanner was stricter than the YAML spec about.
Measured so far: a tab used as a token separator (`name:<TAB>value`, a
trailing tab, a tab before a `#` comment), a `?` inside a flow
collection (`globs: [tests/?_*.py]`), and a block-scalar header followed
by `#`. That list is what has been measured, not a boundary — if a file
of yours stopped reporting a parse error, this is why.

The spec permits the first two, so for those the new behaviour is the
correct one and the file is fine as written. The third is the other way
round: a comment must be preceded by whitespace, so `a: |#` is malformed
YAML that libyaml accepts anyway. If that is your file, **fix it**
(`a: | #`) rather than baselining what it now reports — another parser
may still reject it.

Either way, a file whose frontmatter previously failed to parse now has
its fields checked, and any violation that surfaces is not in your
baseline. The reverse also holds: a `coderabbit-yaml-valid` (or other
parse-validity) error that your baseline suppresses can *disappear*,
because the file now parses. A baseline entry for a violation that no
longer fires is stale rather than harmful, but it will not be pruned for
you.

**One caveat on reproducibility.** The loader is chosen at import time
from whether the installed PyYAML carries its C extension. Nearly every
wheel does, but a source build — some musl or hardened environments —
falls back to the pure-Python scanner and keeps the stricter behaviour.
The same skillsaw version can therefore reach different verdicts about
the same file on two machines. If CI and a laptop disagree about a parse
error, compare `python -c "import yaml; print(hasattr(yaml, 'CSafeLoader'))"`
on both before looking anywhere else.

### The other direction: files that stop parsing

Parsing is now bounded at 100 levels of nesting, measured over both the
document's own structure and the object graph its aliases build (a chain
of anchors is two levels as text and any depth at all as an object). A
document past that bound is **not** malformed — earlier versions parsed
and linted it — but skillsaw now declines to, and reports that it did.
The bound exists because the C parser underneath has no recursion guard
and a deep enough document takes the process down with it, which is worse
than a refusal.

If you hit this, the message says so explicitly ("Frontmatter nesting
exceeds the 100-level reader bound"). Flatten the document; the bound is
not configurable.

If your baseline predates the upgrade and CI fails on violations you did
not introduce, re-run `skillsaw baseline` to take them up, then fix them
on your own schedule. A tab used as *indentation* is still an error, as
it is in every YAML version.

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
