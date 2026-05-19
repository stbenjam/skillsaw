---
name: release-notes
description: Generate release notes from git log between two tags or refs
---

# Release Notes Generator

Produces structured release notes from the git history between two
references (tags, branches, or commits).

## When to Use

Invoke this skill when the user asks to generate release notes, a
changelog, or a summary of changes between two points in history.

## Implementation Steps

### Step 1: Determine the Range

Ask the user for the start and end refs. If not provided, default to
the range between the two most recent tags:
```bash
git describe --tags --abbrev=0
git describe --tags --abbrev=0 HEAD~1
```

### Step 2: Collect Commits

Run `git log --format="%h %s (%an)" $START..$END` to list commits.

### Step 3: Categorize

Group commits by conventional-commit prefix:
- `feat:` → Features
- `fix:` → Bug Fixes
- `docs:` → Documentation
- `refactor:` → Internal Changes

### Step 4: Format Output

Produce a markdown document with sections for each category, listing
each change with its short hash and author.
