## Why

Emphasis works by contrast. A file where a handful of directives carry
`IMPORTANT` or `NEVER` tells the model exactly which rules are
load-bearing; a file where most lines shout tells it nothing — when
everything is emphasized, nothing is. Frontier-model prompting guidance
(e.g. OpenAI's GPT-5.6 prompting guide) recommends removing absolute
directives used as blanket steering: recent models follow prompt
contracts closely, and emphasis inflation just adds noise.

The rule counts lines containing critical-emphasis keywords
(`IMPORTANT`, `MUST`, `NEVER`, `ALWAYS`, `CRITICAL`, `WARNING`,
`REQUIRED` — uppercase only; prose-case "never do X" is a normal
directive and doesn't count) and flags the file when they exceed a
configurable fraction of its non-blank lines. Short bursts are exempt:
the rule stays silent below a minimum count of emphasized lines, so a
small file with a couple of MUSTs is fine.

This complements `content-critical-position`, which checks *where*
critical instructions sit; this rule checks *how many* there are.

## Examples

**Bad (everything is critical):**

```markdown
## Rules
- IMPORTANT: run the tests before committing.
- You MUST update the OpenAPI spec when handlers change.
- NEVER log request bodies.
- ALWAYS regenerate mocks after interface edits.
- CRITICAL: keep migrations reversible.
- WARNING: staging shares a message bus with production.
```

**Good (emphasis reserved for the one rule that needs it):**

```markdown
## Rules
- Run the tests before committing.
- Update the OpenAPI spec when handlers change.
- NEVER log request bodies — they contain customer addresses.
- Regenerate mocks after interface edits.
- Keep migrations reversible.
- Staging shares a message bus with production.
```

## How to fix

1. Demote most emphasized lines to plain directives — an instruction
   file is already authoritative; "Update the spec" binds exactly as
   much as "You MUST update the spec".
2. Keep uppercase emphasis only on the few rules whose violation is
   irreversible or dangerous, and say *why* ("NEVER log request
   bodies — they contain customer addresses").
3. If a rule truly must never be violated, consider enforcing it with
   a hook instead of prose (see `content-hook-candidate`).

Tune the rule in `.skillsaw.yaml`:

```yaml
rules:
  content-emphasis-density:
    severity: warning
    max-ratio: 0.2       # flag when >20% of non-blank lines are emphasized
    min-emphasized: 5    # never flag fewer than 5 emphasized lines
```
