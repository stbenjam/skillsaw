---
description: Scan documentation for broken references
argument-hint: "[path]"
---

## Name
doc-checker:scan

## Synopsis
```text
/doc-checker:scan docs/
```

## Description
Scans the given documentation tree for broken links, references to files
that no longer exist, and code examples that have drifted from the source.

## Implementation
1. Collect all markdown files under the given path
2. Extract links and file references from each document
3. Verify each reference resolves within the repository
4. Compare fenced code examples against the referenced source files
5. Print a report of broken references grouped by document
