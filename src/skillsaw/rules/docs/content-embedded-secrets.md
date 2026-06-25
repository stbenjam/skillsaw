## Why

Instruction files are checked into version control and often read by
multiple agents and users. A hardcoded API key, token, or password in an
instruction file is a credential leak — it is visible in the git history
even after removal and may be harvested by automated scanners.

## Examples

**Bad:**

```markdown
Set the API key to `sk-abc123...` in your environment.
```

**Good:**

```markdown
Set the API key via the `OPENAI_API_KEY` environment variable.
Store secrets in `.env` (gitignored) — never inline them in instruction
files.
```

## How to fix

Replace the hardcoded secret with an environment variable reference
(e.g., `$API_KEY`) or a note directing the reader to a secure storage
mechanism. Rotate the exposed credential immediately — removing it from
the file does not remove it from git history. `skillsaw fix --llm` can
redact detected secrets automatically.
