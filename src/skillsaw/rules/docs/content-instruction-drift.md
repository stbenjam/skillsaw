## Why

Teams often copy a section between instruction files — CLAUDE.md,
AGENTS.md, GEMINI.md, `.github/copilot-instructions.md`,
`.cursor/rules/*.mdc`, `.claude/rules/*.md` — so every assistant gets
the same guidance. Then someone edits one copy and forgets the others.
The copies silently disagree, and different agents follow different
rules for the same task.

Exactly identical sections are fine: that is intentional sync.
Near-identical sections (similar but not equal after normalization) are
the bug this rule catches — one copy drifted.

This differs from neighboring rules: `content-contradiction` matches
known contradictory phrase pairs, `content-inconsistent-terminology`
flags mixed term variants, and `content-redundant-with-tooling` flags
instructions better enforced by tool config. This rule compares whole
sections across files for structural near-duplication.

## Examples

**Bad (drifted copies):**

```markdown
<!-- CLAUDE.md -->
## Testing
Run the full suite with `make test` before every push. Integration
tests require Docker; start it with `make docker-up` first. Never skip
failing tests — fix them or file an issue with the failure output.

<!-- .github/copilot-instructions.md -->
## Testing
Run the full suite with `make test` before every push. Integration
tests require Docker; start it with `make docker-up` first.
```

One copy gained a sentence about failing tests; the other never got it.

**Good (identical copies, intentionally synced):**

```markdown
<!-- Both files -->
## Testing
Run the full suite with `make test` before every push. Integration
tests require Docker; start it with `make docker-up` first. Never skip
failing tests — fix them or file an issue with the failure output.
```

## How to fix

Compare the two sections named in the violation and reconcile them:

1. Decide which copy is current (usually the most recently edited one).
2. Update the stale copy to match exactly, or rewrite both if neither
   is fully right.
3. Better: keep one source of truth. Generate the copies with a
   compiler such as [APM](https://github.com/danielmeppiel/apm) — files
   carrying a "generated ... do not edit" marker are skipped by this
   rule — or replace the duplicated section with a short pointer to a
   single shared file.

**Intentional harness-specific divergence.** Sometimes two copies are
*supposed* to differ — e.g. CLAUDE.md says "Claude Code style tool
names" where AGENTS.md says "Codex style tool names". Suppress that
section with a standard inline directive in the file the violation is
reported on (the later file in path order — or both files, to be safe):

```markdown
<!-- skillsaw-disable content-instruction-drift -->
## Tool naming
...harness-specific content...
<!-- skillsaw-enable content-instruction-drift -->
```

The directive comment itself never affects the comparison: HTML
comments and whitespace are stripped before sections are compared, so
adding a suppression to one file cannot create (or hide) drift
distance in another pair.

Tune the rule in `.skillsaw.yaml`:

```yaml
rules:
  content-instruction-drift:
    severity: warning
    similarity-threshold: 0.85   # 0-1 exclusive; higher = only very close copies fire
    min-section-words: 60        # ignore sections shorter than this
    ignore-generated: true       # skip files with a generated-file marker
```
