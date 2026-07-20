## Why

Agents follow instructions literally. "Keep monitoring the PR for
feedback" with no bound tells an agent to loop forever — burning
tokens, holding a session open, or polling an API until something
external kills it. Frontier-model prompting guidance (e.g. OpenAI's
GPT-5.6 prompting guide) lists stopping conditions and success criteria
among the few things a prompt should always keep: define the
destination, not just the activity.

The rule finds open-ended loop instructions — "keep monitoring",
"keep checking", "poll for", "continuously", "retry when" — and flags
them when the surrounding paragraph contains no stopping condition: no
"until", no "stop after N minutes", no "at most N attempts", no
count, timeout, or exit criteria.

This rule is **opt-in** (`enabled: false` by default): monitoring
language is common in prose that never reaches an agent verbatim.
Enable it for repositories whose instruction files drive autonomous
agents.

## Examples

**Bad (unbounded loop):**

```markdown
After opening a PR, keep monitoring for reviewer feedback and address
comments as they arrive.
```

**Good (bounded — same activity, explicit stop):**

```markdown
After opening a PR, keep monitoring for reviewer feedback and address
comments as they arrive. You may stop monitoring 20 minutes after the
last push.
```

**Good (bounded retry):**

```markdown
Retry when the smoke-test job fails with a registry pull error; give
up after 3 attempts and page the infra channel instead.
```

## How to fix

Add the bound in the same paragraph as the loop instruction. Any of
these forms count:

- a condition: "until CI passes", "stop once the PR merges"
- a count: "at most 3 retries", "up to 5 times"
- a time budget: "for 20 minutes", "stop after 1 hour", "with a
  10-minute timeout"

Tune the rule in `.skillsaw.yaml`:

```yaml
rules:
  content-missing-stop-condition:
    enabled: true
    severity: warning
    extra-loop-patterns:          # project phrasing that starts a loop
      - '\bbabysit\b'
    extra-terminator-patterns:    # project phrasing that bounds one
      - '\bend\s+of\s+shift\b'
```
