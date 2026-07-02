## Why

Instruction files are checked into version control and often read by
multiple agents and users. A hardcoded API key, token, or password in an
instruction file is a credential leak — it is visible in the git history
even after removal and may be harvested by automated scanners.

## Detection

Two classes of match are handled differently:

- **Structured token formats** (`AKIA…`, `ghp_…`, `sk-ant-…`, private-key
  blocks, JWTs, …) are high-confidence and always reported.
- **Generic credential assignments** (`password = "…"`, `api_key: "…"`,
  `secret_key`, `access_token`) are gated to avoid flagging documentation
  examples:
    - *Placeholder allowlist*: values containing obvious placeholder
      markers (`example`, `placeholder`, `dummy`, `changeme`, `your-…`,
      `hunter2`, …), template syntax (`<your-key>`, `${VAR}`,
      `{{ var }}`), or a single repeated character are skipped. Extend
      the list with `additional-placeholders`.
    - *Entropy gating*: the value's Shannon entropy must reach
      `entropy-threshold` (default 3.5 bits/char). Real random secrets
      pass; English-ish placeholder strings do not. Values shorter than
      16 characters are length-normalized before comparison (per-char
      Shannon entropy of an n-char string is capped at log2(n), so a
      fully random 10-char password measures only ~3.3 bits/char raw —
      short random passwords still fire).

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
the file does not remove it from git history. A coding agent can
redact detected secrets automatically.
