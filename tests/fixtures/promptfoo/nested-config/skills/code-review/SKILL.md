---
name: code-review
description: Review code changes for correctness, style, and potential issues
---

# Code Review

Analyze the provided code diff and produce a structured review covering:

1. **Correctness** — logic errors, off-by-one mistakes, null-safety gaps
2. **Style** — naming conventions, formatting, idiomatic usage
3. **Performance** — unnecessary allocations, O(n²) patterns, missing indexes
4. **Security** — injection vectors, credential leaks, auth bypasses

Output a markdown summary with severity ratings for each finding.
