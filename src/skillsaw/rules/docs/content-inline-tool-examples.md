## Why

Anthropic's Claude 5 context-engineering guidance recommends moving from
example-driven prompting to interface design: "Giving examples actually
constrains them to a certain exploration space." A wall of near-identical
example invocations teaches the model three points in an argument space
and implicitly discourages everything in between; a description of the
tool's parameters, types, and constraints covers the whole space in
fewer tokens. Modern models infer usage from an interface — they don't
need the same call demonstrated with three different query strings.

The rule looks at fenced (and indented) code blocks whose content is
call-syntax invocations of a single tool or function — `search(...)`,
`client.messages.create(...)` — and flags a run of `min-consecutive` or
more adjacent blocks that all invoke the same callee, differing only in
their arguments. Blocks separated by a heading, or by more than
`max-lines-between` non-blank prose lines (caption lines like "Another
example:" don't break the run), are not considered adjacent. Fences
containing ordinary code — imports, control flow, calls to more than one
function — never participate.

The rule is opt-in: tutorial-style skills legitimately walk through
usage examples, and only the author knows whether a file is a tutorial
or an interface reference.

## Examples

**Bad (three examples, one tool, only the arguments change):**

```markdown
## Using the search tool

When you need to find a symbol, use the search tool. For example:

    search(query="TransferFunds", type="symbol")

Another example, searching for a file:

    search(query="ledger.go", type="file")

A third example, searching text:

    search(query="fixed-point", type="text")
```

**Good (one description of the interface):**

```markdown
## Using the search tool

Search with `search(query, type)` — `type` is one of `symbol`, `file`,
or `text`. Queries are literal strings, not regexes.
```

## How to fix

1. Replace the run of examples with a description of the tool's
   interface: parameter names, accepted values or types, and any
   constraints ("queries are literal, not regex").
2. Keep at most one example if the calling convention is genuinely
   non-obvious — one is enough to show the syntax.
3. If the file is a tutorial that deliberately walks through several
   invocations, leave it as is — this rule is opt-in precisely because
   that style is sometimes the point.

Tune the rule in `.skillsaw.yaml`:

```yaml
rules:
  content-inline-tool-examples:
    enabled: true
    min-consecutive: 3    # flag runs of 3+ same-tool example blocks
    max-lines-between: 2  # prose lines allowed between blocks in a run
```
