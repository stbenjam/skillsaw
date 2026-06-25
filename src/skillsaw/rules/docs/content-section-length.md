## Why

Long, unbroken sections exceed the model's working-memory span for
a single topic. When a section runs past ~500 tokens, instructions
near its end compete with instructions near its start for the model's
attention — and the ones in the middle lose.

## Examples

**Bad:**

A single `## Setup` section spanning 200 lines covering environment,
dependencies, database, Docker, and CI configuration.

**Good:**

```markdown
## Environment setup
...

## Database setup
...

## Docker
...
```

## How to fix

Split long sections into focused subsections, each under its own
heading one level deeper than the parent. Aim for roughly 10–30 lines
per subsection. `skillsaw fix --llm` can add headings automatically.

## Tuning

Adjust the token threshold per section:

```yaml
rules:
  content-section-length:
    max-tokens: 800
```
