---
name: report-builder
description: Build weekly status reports from git history and issue tracker exports
compatibility: Requires Python 3.9+ and git
metadata:
  author: dx-team
  version: "1.0"
---

# Report Builder

Build a weekly status report from git history and an issue tracker
export.

## When to Use This Skill

Use when the user asks for a weekly status report, a sprint summary,
or a change digest for a repository.

## Implementation Steps

### Step 1: Collect the Data

Run the bundled builder to collect commits and issue updates:

```bash
python scripts/build.py --since "1 week ago" --output report.html
```

### Step 2: Apply the House Style

Follow the formatting rules in [the style guide](references/guide.md)
when editing the generated sections. HTML templates for the report
shell live in the `assets/` directory.

### Step 3: Deliver

Attach the generated `report.html` and paste the summary section into
the status channel.
