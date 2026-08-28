## Why

Claude Code reads `CLAUDE.md`; almost every other agent reads `AGENTS.md`.
Keeping both means maintaining two copies of the same instructions, and the
copies drift. Claude Code's `@path` import syntax removes the duplication:
a `CLAUDE.md` whose whole body is `@AGENTS.md` gives one source of truth
that every assistant reads.

`content-instruction-drift` is the detector for what happens without this —
it reports sections that have already grown apart. This rule recommends the
structure under which they cannot. An import-only `CLAUDE.md` has no
sections to compare, so both rules are silent on it.

Severity is INFO: keeping Claude-specific content is a legitimate choice,
not a defect.

## Examples

**Bad** — two full copies of the same instructions:

```markdown
<!-- AGENTS.md and CLAUDE.md both contain: -->
# Project instructions

## Testing
Run `make test` before every push.
```

**Good** — the whole of `CLAUDE.md`:

```markdown
@AGENTS.md
```

Blank lines and HTML comments never count as content, so a banner or a
suppression directive above the import still reads as import-only.
Everything else does count: a heading, a sentence, a code fence. A
`CLAUDE.md` symlinked to `AGENTS.md` is one file under two names and is
never reported.

## How to fix

Move anything `CLAUDE.md` has that `AGENTS.md` lacks into `AGENTS.md`, then
replace the body of `CLAUDE.md` with a single `@AGENTS.md` line.
`instruction-imports-valid` checks that the import resolves.

When `CLAUDE.md` is already a byte-for-byte copy (identical after trailing
whitespace is stripped), `skillsaw fix --suggest` does this for you. It is
SUGGEST, not SAFE — replacing a file's contents is a judgment call, so
plain `skillsaw fix` never does it, and anything that is not an exact copy
is reported only.

To keep Claude-specific sections, put the import first and set:

```yaml
rules:
  claude-md-agents-import:
    allow-extra: true       # accept the import plus extra content
    ignore-generated: true  # skip a compiled CLAUDE.md (default)
```

Or disable the rule and keep `content-instruction-drift` to be told when
the copies diverge.
