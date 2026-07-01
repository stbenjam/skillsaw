## Why

A low actionability score means the file reads more like documentation than
instructions. Models follow imperative statements with specific commands and
file paths far more reliably than passive descriptions. Instruction files
that score below the threshold are likely to be partially ignored because
the model cannot translate vague prose into concrete actions.

## Examples

**Bad:**

```markdown
The project has a testing framework that should be used.
Code quality is important for this repository.
```

**Good:**

```markdown
Run `npm test` before committing.
Use ESLint (`npm run lint`) to check code quality.
See `src/config.ts` for the project's shared configuration.
```

## How to fix

Add imperative verbs, inline commands (backticked), and file path
references. Replace descriptions with direct instructions. A coding agent can rewrite low-scoring files automatically.
