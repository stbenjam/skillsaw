## Why

Models treat hedged instructions as optional. Phrases like "try to", "if
possible", "maybe consider", or "it would be good to" introduce ambiguity
about whether an instruction is mandatory, and the model resolves that
ambiguity by skipping the instruction whenever it conflicts with anything
else in context. Direct, assertive language measurably improves
instruction-following: Bsharat et al. found direct phrasing ("Your task
is", "You MUST") yielded a 57.7% quality improvement over hedged
equivalents.

## Examples

**Bad:**

```markdown
Try to run the tests before committing, if possible.
Consider using the project's logging helpers where appropriate.
```

**Good:**

```markdown
Run the tests before committing.
Use the project's logging helpers.
```

## When not to flag

Genuinely conditional guidance is fine when the condition is concrete —
"If the build fails, check the lockfile first" is actionable, not hedged.
The rule targets hedges that leave the decision to the model, not
conditions the model can evaluate.

## How to fix

Rewrite the instruction as an imperative: state what to do, not what to
attempt. If you cannot state it unconditionally, spell out the concrete
condition instead of hedging. `skillsaw fix --llm` can rewrite flagged
lines automatically.
