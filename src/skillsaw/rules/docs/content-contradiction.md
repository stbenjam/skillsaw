## Why

When two instructions in the same file contradict each other, the model
must pick one and discard the other — silently. The choice is
unpredictable and context-dependent, so the losing instruction is
effectively deleted from the agent's behavior without anyone noticing.

## Examples

**Bad:**

```markdown
Move fast and ship frequently.
Write comprehensive tests for every change.
```

**Good:**

```markdown
Write focused tests for critical paths — prioritize coverage of public
API boundaries over internal helpers.
```

## How to fix

Resolve the contradiction by choosing the more specific instruction, or
merge both into a single statement with appropriate context. If both are
valid in different situations, add explicit conditions. `skillsaw fix
--llm` can rewrite contradictory pairs automatically.
