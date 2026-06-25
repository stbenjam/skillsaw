## Why

A bare path like `src/config.ts` in prose is not clickable and not
machine-navigable. Wrapping it in markdown link syntax
(`[src/config.ts](src/config.ts)`) makes it a navigable reference
that tools and agents can follow to read the file's contents.

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
violation message says "file exists, autofixable", `skillsaw fix` can
wrap it automatically. For paths that do not exist, verify the path
is correct before linking.
