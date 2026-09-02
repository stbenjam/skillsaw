## Why

Stating the same instruction multiple times doesn't improve model
adherence. Modern prompting guides (such as OpenAI's GPT-5.6 prompting guide)
recommend stating each instruction once clearly. Repetitive directives add
unnecessary tokens and can create conflicting nuances without improving
behavior. Every repeat also uses instruction budget that could be used for
other rules (see `content-instruction-budget`).

The rule detects two forms of repetition within a single file:

- **Repeated directives** — two imperative lines that are identical or
  nearly identical after normalization (markdown stripped, lowercased).
- **Restated policies** — two different lines that match the same
  phrase cluster (such as the built-in `approval` cluster: "ask first/before",
  "wait for approval", "confirm before", or "do not proceed without approval").

Directives are compared line by line across sections within a file. Both forms
report at **info**: deciding whether two similar instructions are redundant
or intentionally distinct is a developer choice, so the rule surfaces the
opportunity without failing a build. You can raise `severity` to `warning` or
`error` in `.skillsaw.yaml` for stricter enforcement; phrase cluster
restatements stay at info.

Intentional parallel structures (such as neighboring list items, parameterized code
examples, or section captions directly above code blocks) are excluded from comparison.

This differs from neighboring rules: `content-instruction-drift` compares whole sections
*across* files, whereas this rule compares individual directives *within* one file.


## Examples

**Bad (one directive stated twice, one policy stated two ways):**

```markdown
## Testing
- Run `make test` before every push.

## Releases
- Run `make test` before every push.
- Ask before force-pushing to a shared branch.

## Cleanup
- Wait for approval before deleting production data.
```

**Good (each instruction and policy stated once):**

```markdown
## Testing
- Run `make test` before every push (this covers releases too).

## Approvals
- Ask before force-pushing to a shared branch or deleting
  production data.
```

## How to fix

1. Keep the statement in the most load-bearing location (usually the
   dedicated section) and delete the other occurrences.
2. If the repeats were scoped differently ("ask before X", "ask before
   Y"), merge them into one policy statement listing the cases.
3. If two sections genuinely need the reminder, make one of them a
   short pointer to the other instead of a restatement.

Tune the rule in `.skillsaw.yaml`:

```yaml
rules:
  content-repeated-directive:
    severity: warning            # default is info; raise it to fail a build
    similarity-threshold: 0.9    # (0-1]; higher = only near-verbatim repeats fire
    min-directive-words: 5       # ignore directives shorter than this
    min-line-distance: 4         # don't compare directives closer than this
    similarity-max-directives: 1500  # cap on directives entering pairwise comparison
    extra-clusters:              # project-specific restatement clusters
      deploy-source:
        - '\b(?:deploy|ship)\s+(?:only|exclusively)\b'
```

`similarity-max-directives` caps the number of directives evaluated per file (default 1500).
Raise this setting if you maintain exceptionally large instruction files.

Suppress an intentional repeat (e.g. a safety-critical reminder you
want in both places) with an inline directive:

```markdown
<!-- skillsaw-disable-next-line content-repeated-directive -->
- Run `make test` before every push.
```
