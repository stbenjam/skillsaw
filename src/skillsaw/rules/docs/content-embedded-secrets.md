## Why

Instruction files are checked into version control and often read by
multiple agents and users. A hardcoded API key, token, or password in an
instruction file is a credential leak — it is visible in the git history
even after removal and may be harvested by automated scanners.

## Detection

Two classes of match are handled differently:

- **Structured token formats** (`AKIA…`, `ghp_…`, `sk-ant-…`, private-key
  blocks, JWTs, …) are high-confidence and reported unless the complete
  candidate is an exact, audited documentation literal. The canonical AWS
  documentation access-key ID and a standalone `-----BEGIN RSA PRIVATE KEY-----`
  header are permitted; close variants and PEM blocks followed by key material
  still report.
- **Generic credential assignments** (`password = "…"`, `api_key: "…"`,
  `secret_key`, `access_token`) are gated to avoid flagging documentation
  examples:
    - *Placeholder allowlist*: values containing obvious substring markers
      (`example`, `placeholder`, `dummy`, `changeme`, `your-…`, …), template
      syntax (`<your-key>`, `${VAR}`, `{{ var }}`), or a single repeated
      character are skipped. Extend the substring list with
      `additional-placeholders`.
    - *Audited examples*: exact values (`hunter2`, `sk_live_abc123xyz789`,
      `sk_live_abc123def456`, and the literal three-dot value
      `django-insecure-...`) are skipped after trimming surrounding whitespace
      and comparing case-insensitively. Close variants remain reportable.
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
