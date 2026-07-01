## Why

Models process grouped instructions more reliably than flat lists.
Section headings act as cognitive anchors — they help the model
compartmentalize instructions by topic and retrieve the right ones when
a task matches a heading. Unstructured files force the model to scan
everything linearly, increasing the chance of missed instructions.

## Examples

**Bad:**

```markdown
Run tests before committing.
Use ESLint for linting.
Deploy with `make deploy`.
All PRs need two approvals.
Use feature branches.
```

**Good:**

```markdown
## Testing

Run tests before committing.

## Code style

Use ESLint for linting.

## Deployment

Deploy with `make deploy`.
```

## How to fix

Add markdown headings (`##`) to group related instructions by topic.
Aim for 10–30 lines per section. If the file has only one heading,
break it into task-oriented subsections. A coding agent can add
headings automatically.
