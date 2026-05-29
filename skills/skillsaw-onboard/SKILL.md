---
name: skillsaw-onboard
description: "Onboard a repository to skillsaw — run the linter, apply autofixes, manually fix remaining violations, set up CI, and create a baseline. Use when adopting skillsaw on a new or existing project."
compatibility: "Requires skillsaw (uvx skillsaw or pip install skillsaw). Optional: gh CLI for GitHub Actions setup, LLM access for content fixes."
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Onboard

You are onboarding this repository to **skillsaw**, a linter for agentic
contextual building blocks (CLAUDE.md, skills, plugins, agents, hooks, etc.).

Work through each step in order. Communicate progress to the user at each stage.

## Step 1: Initial scan

Run `skillsaw tree` to see what skillsaw detects in this repo — the repo type,
instruction files, plugins, skills, and other components. Show the user a brief
summary of what was found.

Then run `skillsaw` (lint) and capture the full output. Count the errors and
warnings. If the repo has zero violations, congratulate the user and skip to
Step 5 (CI setup).

## Step 2: Apply deterministic autofixes

Run `skillsaw fix` to apply safe, deterministic fixes (e.g. adding missing
frontmatter, fixing names to kebab-case, registering unregistered plugins).

After fixing, run `skillsaw` again to see what remains. Report to the user:
- How many violations were auto-fixed
- How many violations remain

If all violations are resolved, skip to Step 5.

## Step 3: Fix remaining violations manually

For each remaining violation, attempt to fix it directly. You are an AI agent —
you can read and edit the files yourself. Common fixes include:

<!-- skillsaw-disable content-weak-language, content-tautological -->
- **Weak language** (`content-weak-language`): Remove hedging words like "try
  to", "you might want to", "consider", "maybe". Rewrite as direct imperatives.
- **Tautological statements** (`content-tautological`): Remove empty truisms
  like "follow best practices" or "ensure code quality". Replace with specific,
  actionable instructions or delete the line entirely.
<!-- skillsaw-enable content-weak-language, content-tautological -->
- **Vague references** (`content-vague-reference`): Replace vague phrases like
  "the relevant files" or "appropriate tools" with specific names.
- **Missing descriptions** or **missing fields**: Add the required content.
- **Structural issues**: Fix directory names, file naming, missing files.

For each fix:
1. Read the file and understand the context around the violation
2. Make a targeted edit that fixes the violation without changing surrounding meaning
3. Keep edits scoped to the violation — do not rewrite entire files

After fixing all violations you can address, run `skillsaw` again to confirm
they are resolved. If violations remain that you cannot fix (e.g. they require
user decisions about content), list them for the user and explain what needs to
change.

## Step 4: Baseline remaining violations

If any violations remain after Steps 2–3, offer to create a baseline:

Tell the user: "There are N remaining violations. I can create a baseline file
(`.skillsaw-baseline.json`) so these are accepted for now — only *new*
violations will fail going forward. You can fix them over time and re-run
`skillsaw baseline` to shrink the accepted set."

If the user agrees, run `skillsaw baseline` and confirm the file was created.
Remind them to commit `.skillsaw-baseline.json` to the repository.

## Step 5: Generate configuration

If no `.skillsaw.yaml` exists yet, run `skillsaw init` to generate a default
config file. Tell the user they can customize rule settings in this file.

If one already exists, skip this step.

## Step 6: Set up CI

Ask the user which CI system they use. Offer the following options:

### GitHub Actions

Create `.github/workflows/lint.yml`:

```yaml
name: Lint

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  skillsaw:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          persist-credentials: false
      - uses: stbenjam/skillsaw@v0
        with:
          strict: true
```

Then ask if they also want PR review comments. If yes, also create
`.github/workflows/lint-review.yml`:

```yaml
name: Lint Review

on:
  workflow_run:
    workflows: ["Lint"]
    types: [completed]

jobs:
  review:
    if: github.event.workflow_run.event == 'pull_request'
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: stbenjam/skillsaw/review@v0
```

### GitLab CI

Add a `skillsaw` job to `.gitlab-ci.yml`. Use the `code-climate` output format
with a GitLab Code Quality artifact so violations appear inline on merge
requests:

```yaml
skillsaw:
  image: ghcr.io/stbenjam/skillsaw:latest
  stage: test
  script:
    - skillsaw --strict --output gitlab:gl-code-quality.json
  artifacts:
    reports:
      codequality: gl-code-quality.json
```

### No CI / Skip

If the user declines CI setup, skip this step. Mention they can set it up later
by following the skillsaw CI documentation.

## Step 7: Final verification

Run `skillsaw` one final time and confirm the repo passes (exit 0). Summarize
what was done:

- Number of violations found initially
- Number fixed automatically
- Number fixed manually
- Number baselined
- CI setup (if any)
- Files created or modified

Remind the user to commit all new/changed files:
- `.skillsaw.yaml` (if created)
- `.skillsaw-baseline.json` (if created)
- `.github/workflows/lint.yml` (if created)
- `.github/workflows/lint-review.yml` (if created)
- `.gitlab-ci.yml` (if modified)
- Any files that were fixed
