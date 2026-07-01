## Why

Research on instruction-following shows compliance degrades as the number
of simultaneous instructions grows. Beyond roughly 150 imperative
instructions in a single file, the model begins silently dropping or
deprioritizing rules. Staying within budget ensures every instruction
actually influences behavior.

## Examples

**Bad:**

A CLAUDE.md with 200+ imperative lines covering every edge case.

**Good:**

A CLAUDE.md with ~80 focused instructions, with rarely-needed rules moved
to `.claude/rules/` files that load only when relevant.

## How to fix

Merge duplicate instructions, remove tautologies (things the model does
by default), and move context-specific rules into scoped rule files
(`.claude/rules/`) so they only load when relevant. A coding agent
can consolidate instructions automatically.
