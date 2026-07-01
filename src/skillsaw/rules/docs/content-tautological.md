## Why

Instructions that restate a model's default behavior ("write clean code",
"be helpful", "follow best practices") add tokens without changing
behavior. Every instruction in a context file competes for the model's
attention; research on instruction-following shows compliance degrades as
the number of simultaneous instructions grows. Tautological lines crowd
out the instructions that actually encode project-specific knowledge.

## Examples

**Bad:**

```markdown
Write clean, maintainable code.
Always be careful when making changes.
Follow software engineering best practices.
```

**Good:**

```markdown
Match the existing error-handling style: return `Result` types, never
raise exceptions across crate boundaries.
```

## How to fix

Delete the line, or replace it with the project-specific rule you
actually meant. Ask: "would any competent model ever do the opposite of
this on purpose?" If not, the instruction is a tautology. A coding agent can rewrite or remove flagged lines.
