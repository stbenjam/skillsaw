## Why

Claude Code reads `CLAUDE.md`; almost every other agent reads `AGENTS.md`.
Keeping both means maintaining two copies of the same instructions, and the
copies drift. Claude Code's `@path` import syntax removes the duplication:
a `CLAUDE.md` can import `AGENTS.md` and keep any Claude-specific instructions
below it. Shared guidance then has one source of truth.

`content-instruction-drift` is the detector for what happens without this —
it reports sections that have already grown apart. This rule recommends the
structure under which they cannot. An import-only `CLAUDE.md` has no
sections to compare, so both rules are silent on it.

Severity is INFO because importing the shared file is a maintainability
recommendation, not a correctness requirement.

## Examples

**Bad** — two full copies of the same instructions:

```markdown
<!-- AGENTS.md and CLAUDE.md both contain: -->
# Project instructions

## Testing
Run `make test` before every push.
```

**Good** — shared guidance plus Claude-specific instructions:

```markdown
@AGENTS.md

## Claude Code

Use plan mode for changes under `src/billing/`.
```

An import-only file is also valid. A `CLAUDE.md` symlinked to `AGENTS.md` is
one file under two names and is never reported.

## How to fix

Add an `@AGENTS.md` import. Keep shared instructions in `AGENTS.md` and put
Claude-specific instructions below the import. `instruction-imports-valid`
checks that the import resolves.

When `CLAUDE.md` is already a byte-for-byte copy (identical after trailing
whitespace is stripped), `skillsaw fix --severity info --suggest` does this
for you. The fix needs both opt-ins: this rule reports at info severity,
which plain `skillsaw fix` leaves untouched, and the fix is SUGGEST, not
SAFE — replacing a file's contents is a judgment call. Anything that is not
an exact copy is reported only.

To require an import-only `CLAUDE.md`, set:

```yaml
rules:
  claude-md-agents-import:
    allow-extra: false      # require the import to be the whole file
    ignore-generated: true  # skip a compiled CLAUDE.md (default)
```

Or disable the rule and keep `content-instruction-drift` to be told when
the copies diverge.
