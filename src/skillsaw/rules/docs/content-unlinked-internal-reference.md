## Why

A bare path like `src/config.ts` in prose is not clickable and not
machine-navigable. Wrapping it in markdown link syntax
(`[src/config.ts](src/config.ts)`) makes it a navigable reference
that tools and agents can follow to read the file's contents. The rule only
reports paths that resolve to an existing target inside the repository, so
technology names and illustrative paths do not create unactionable findings.

## Examples

**Bad:**

```markdown
See src/config.ts for the shared configuration.
```

**Good:**

```markdown
See [src/config.ts](src/config.ts) for the shared configuration.
```

## How to fix

Wrap the bare path in markdown link syntax: `[path](path)`. When the
violation message says "file exists, autofixable", skillsaw can wrap it
automatically — at this rule's default info severity that takes
`skillsaw fix --severity info`, since plain `skillsaw fix` only repairs
errors and warnings. Paths without a resolvable local target are ignored.
