---
name: code-review
description: Review pull request diffs for correctness, security, and style
compatibility: Requires git and gh CLI
metadata:
  author: dx-team
  version: "1.0"
---

# Code Review

Review pull request diffs to identify bugs, security issues, and style
violations.

## When to Use This Skill

Use when the user asks to review a PR, check recent changes, or audit
code for quality issues.

## Implementation Steps

### Step 1: Get the Diff

Fetch the diff for the PR or branch:
```bash
gh pr diff $PR_NUMBER
```

Or for local changes:
```bash
git diff main...HEAD
```

### Step 2: Analyze Changes

For each changed file, check for:
- **Logic errors**: off-by-one, null dereference, unchecked returns
- **Security**: SQL injection, XSS, hardcoded secrets, path traversal
- **Style**: naming conventions, import ordering, line length
- **Tests**: new functions without test coverage

### Step 3: Produce Review

Format findings as a structured review:
```text
## file.py:42 — Error: Unchecked return value
The return value of `db.execute()` is ignored. If the query fails,
the function continues with stale data.

**Suggestion:** Add error handling:
\`\`\`python
result = db.execute(query)
if result.error:
    raise DatabaseError(result.error)
\`\`\`
```
