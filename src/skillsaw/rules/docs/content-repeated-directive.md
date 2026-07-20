## Why

Stating the same instruction more than once doesn't make a model follow
it harder. Frontier-model prompting guidance (e.g. OpenAI's GPT-5.6
prompting guide) is explicit: state each instruction once — repeated
directives are noise the model must parse around, and overlapping
restatements of one policy ("ask first" here, "wait for approval"
there) cost reasoning effort without changing behavior. Every repeat
also spends instruction budget that a distinct rule could have used
(see `content-instruction-budget`).

The rule detects two forms of repetition within a single file:

- **Repeated directives** — two imperative lines that are identical or
  nearly identical after normalization (markdown stripped, lowercased).
- **Restated policies** — two different lines that match the same
  phrase cluster. The built-in `approval` cluster covers
  approval-related language: "ask first/before", "wait for approval",
  "confirm before", "do not proceed without approval", and similar.

Directives are compared line by line, so bullet-style instructions are
matched most reliably; a directive buried mid-paragraph is compared
together with the rest of its wrapped line. Inline code is part of the
comparison — `` Run `make test` `` and `` Run `make lint` `` are
different directives.

This differs from neighboring rules: `content-instruction-drift`
compares whole sections *across* files; this rule compares individual
directives *within* one file. `content-contradiction` flags directives
that conflict; this rule flags directives that agree too much.

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
    severity: warning
    similarity-threshold: 0.9    # (0-1]; higher = only near-verbatim repeats fire
    min-directive-words: 5       # ignore directives shorter than this
    extra-clusters:              # project-specific restatement clusters
      deploy-source:
        - '\b(?:deploy|ship)\s+(?:only|exclusively)\b'
```

Suppress an intentional repeat (e.g. a safety-critical reminder you
want in both places) with an inline directive:

```markdown
<!-- skillsaw-disable-next-line content-repeated-directive -->
- Run `make test` before every push.
```
