## Why

The `metadata.openclaw` block in SKILL.md frontmatter registers the
skill with the openclaw ecosystem. Invalid or missing fields mean the
skill will not be indexed correctly, reducing its discoverability
through openclaw-compatible tools.

## Examples

**Bad:**

```yaml
---
name: deploy
description: Deploy to staging
metadata:
  openclaw:
    version: latest
---
```

**Good:**

```yaml
---
name: deploy
description: Deploy to staging
metadata:
  openclaw:
    version: "1.0.0"
    license: MIT
    author: acme-corp
---
```

## How to fix

Add or correct the fields identified in the violation message to
match the
[openclaw spec](https://docs.openclaw.ai/tools/skills). This rule
only fires when `metadata.openclaw` is present — removing the block
suppresses it entirely.
