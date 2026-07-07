---
name: skillsaw-onboard
description: "Onboard a repository to skillsaw — run the linter, apply autofixes, manually fix remaining violations, set up CI, and create a baseline. Use when adopting skillsaw on a new or existing project."
compatibility: "Requires skillsaw (uvx skillsaw or pip install skillsaw). Optional: gh CLI for GitHub Actions setup."
license: Apache-2.0
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Onboard

Onboard this repo to **skillsaw**, a linter for agentic
contextual building blocks (CLAUDE.md, skills, plugins, agents, hooks, etc.).

Follow each step in order, and report progress to the user at each stage.

## Step 1: Install skillsaw

Check whether `skillsaw` is already available by running `skillsaw --version`. If it
is installed, skip to Step 2.

If not installed, choose the best approach for this environment:

1. **uvx (preferred)** — zero-install, works immediately:
   ```
   uvx skillsaw
   ```
   Use `uvx skillsaw` as the command prefix for all subsequent steps (e.g. `uvx skillsaw tree`, `uvx skillsaw fix`).

2. **pip** — install with pip if uvx is not available:
   ```
   pip install skillsaw
   ```

3. **Container (podman or docker)** — use this if neither uvx nor pip is available.
   Use whichever runtime is installed (`podman` or `docker`):
   ```
   podman pull ghcr.io/stbenjam/skillsaw:latest
   podman run -v $(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw
   ```
   The `:Z` suffix relabels the mount for SELinux. Always mount the repo at
   `/workspace` and pass subcommands after the image name (e.g. `podman run -v $(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw tree`).

Verify the installation works by running `skillsaw --version` (or the equivalent for the chosen approach) before proceeding.

## Step 2: Run the initial scan

Run `skillsaw tree` to see what skillsaw detects in this repo — the repo type,
instruction files, plugins, skills, and other components. Review the findings
and keep the user updated with a brief summary.

Then run `skillsaw` (lint) and capture the full output. Count the errors and
warnings. When zero violations remain, congratulate the user and always skip to
Step 6 (config) or Step 7 (CI setup).

## Step 3: Run deterministic autofixes

Run `skillsaw fix` to apply safe, deterministic fixes (e.g. adding missing
frontmatter, fixing names to kebab-case, registering unregistered plugins).

After fixing, run `skillsaw` again to check what remains. Report to the user:
- How many violations skillsaw auto-fixed
- How many violations remain

If all violations are resolved, skip to Step 6.

## Step 4: Review and fix remaining violations manually

For each remaining violation, handle it directly. You are an AI agent —
you can read and edit the files yourself. Common fixes include:

<!-- skillsaw-disable content-weak-language, content-tautological -->
- **Weak language** (`content-weak-language`): Remove hedging words like "try
  to", "you might want to", "consider", "maybe" — use direct imperatives instead.
- **Tautological statements** (`content-tautological`): Remove empty truisms
  like "follow best practices" or "ensure code quality". Replace with specific,
  actionable instructions or delete the line entirely.
<!-- skillsaw-enable content-weak-language, content-tautological -->
- **Vague references** (`content-vague-reference`): remove vague phrases like
  "the relevant files" or "appropriate tools" — use specific names instead.
- **Missing descriptions** or **missing fields**: Add the required content.
- **Structural issues**: create missing files, and fix directory and file names.

For each fix, follow these steps:
1. Read the file and understand the context around the violation
2. Make a targeted edit that fixes the violation without changing surrounding meaning
3. Keep edits scoped to the violation — do not rewrite entire files

After fixing all violations you can address, run `skillsaw` again to confirm
they are resolved. If violations remain that you cannot fix (e.g. they require
user decisions about content), always list them for the user and explain what needs to change.

## Step 5: Create a baseline for remaining violations

If any violations remain after Steps 3–4, offer to create a baseline:

Tell the user: "There are N remaining violations. I can create a baseline file
(`.skillsaw-baseline.json`) so these are accepted for now — only *new*
violations will fail going forward. You can fix them over time and re-run
`skillsaw baseline` to shrink the accepted set."

If the user agrees, run `skillsaw baseline` and confirm the file was created.
Remind them to commit `.skillsaw-baseline.json` to the repo.

## Step 6: Create the configuration

If no `.skillsaw.yaml` exists yet, run `skillsaw init` to generate a default
config file. Tell the user they can configure rule settings in this file.

If one already exists, keep it and skip this step.

## Step 7: Set up CI

Ask the user which CI system they use. Offer the following options:

### GitHub Actions

<!-- skillsaw-disable-next-line content-unlinked-internal-reference -->
Create `.github/workflows/lint.yml`:

Pin actions to commit SHAs for supply-chain protection. Look up the current
SHAs before you create the workflow:

```
git ls-remote --tags https://github.com/actions/checkout.git v5
git ls-remote --tags https://github.com/stbenjam/skillsaw.git v0
```

Use the returned SHAs in the workflow with a trailing `# vN` comment:

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
      - uses: actions/checkout@<CHECKOUT_SHA> # v5
        with:
          persist-credentials: false
      - uses: stbenjam/skillsaw@<SKILLSAW_SHA> # v0
        with:
          strict: true
```

<!-- skillsaw-disable-next-line content-unlinked-internal-reference -->
Then ask if they also want PR review comments. If yes, also create `.github/workflows/lint-review.yml`:

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
      - uses: stbenjam/skillsaw/review@<SKILLSAW_SHA> # v0
```

### GitLab CI

Add a `skillsaw` job to `.gitlab-ci.yml`. Use the `code-climate` output format
and configure a GitLab Code Quality artifact so violations appear inline in merge-request diffs:

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

If the user declines CI setup, skip this step. Mention they can set it up later by following the skillsaw CI documentation.

## Step 8: Add Makefile targets

Ask the user whether to add Makefile targets for running skillsaw locally. If they decline, skip to Step 9.

First, run this to look up the latest skillsaw version to pin against:

```
python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/skillsaw/json'))['info']['version'])"
```

If `python3` is unavailable, run this instead:

```
git ls-remote --tags https://github.com/stbenjam/skillsaw.git 'v*' | sort -t/ -k3 -V | tail -1
```

Ask the user whether they prefer **uvx** or **podman/docker** for the targets.

### Add uvx targets

```makefile
SKILLSAW_VERSION := <LATEST_VERSION>

.PHONY: lint lint-fix
lint:
	uvx skillsaw==$(SKILLSAW_VERSION) --strict

lint-fix:
	uvx skillsaw==$(SKILLSAW_VERSION) fix
```

### Add podman/docker targets

Use whichever container runtime is installed. Pin to the version tag, not `latest`:

```makefile
SKILLSAW_VERSION := <LATEST_VERSION>
CONTAINER_ENGINE ?= $(shell command -v podman 2>/dev/null || echo docker)

.PHONY: lint lint-fix
lint:
	$(CONTAINER_ENGINE) run --rm -v $$(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw:v$(SKILLSAW_VERSION) --strict

lint-fix:
	$(CONTAINER_ENGINE) run --rm -v $$(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw:v$(SKILLSAW_VERSION) fix
```

If a `Makefile` already exists, append the targets. If not, create one. In
either case, never overwrite existing `lint` or `lint-fix` targets — if they
already exist, ask the user what names to use instead (e.g. `skillsaw-lint`).

## Step 9: Add a README badge

Ask the user whether to add a skillsaw grade badge to their README. The badge
shows the repo's letter grade (A+ through F) and refreshes whenever you build the
badge file. If they decline, skip to Step 10.

If they agree, follow these steps:

1. Run `skillsaw badge`. This writes `.skillsaw-badge.json` to the repo root and prints ready-to-paste markdown for two shields.io badge styles.
2. Add the **endpoint badge** markdown (the variant whose color tracks the grade automatically) to `README.md`:
   - If the README already has badges, check near the top for `img.shields.io`,
     `badge.svg`, or similar image links, then add the skillsaw badge on the same
     line or block as the existing badges.
   - If there are no badges yet, add it on its own line directly under the top-level heading.
3. Always link the badge to `https://skillsaw.org/` — the markdown printed by
   `skillsaw badge` already does this; keep that link when placing it.
4. Check whether `skillsaw badge` printed a URL placeholder (no GitHub remote
   detected). If so, the badge renders once you publish `.skillsaw-badge.json`
   at a URL shields.io can fetch — keep the placeholder for them to fill in.

If Makefile targets were set up in Step 8, wire badge regeneration into them:
add a `badge` target using the same command prefix as the other targets, and
make `lint` depend on it so every lint run refreshes the badge file. The
`badge` target runs first and always succeeds, so the file is regenerated even
when the lint fails:

```makefile
.PHONY: badge
badge:
	uvx skillsaw==$(SKILLSAW_VERSION) badge

lint: badge
	uvx skillsaw==$(SKILLSAW_VERSION) --strict
```

Remind the user: the badge reflects the committed `.skillsaw-badge.json`, so always
regenerate it when content changes — run `make lint` (or `skillsaw badge`
directly), or add it to CI (e.g. a workflow step that runs `skillsaw badge` and
commits the file if it changed). The badge ignores any baseline and always
reflects the repo's true grade.

## Step 10: Run the final verification

Run `skillsaw` one final time and confirm the repo passes (exit 0). Summarize what was done:

- Number of violations found initially
- Number fixed automatically
- Number fixed manually
- Number baselined
- CI setup (if any)
- Makefile targets (if any)
- README badge (if added)
- Files created or modified

<!-- skillsaw-disable content-unlinked-internal-reference -->
Remind the user to commit all new/changed files:
- `.skillsaw.yaml` (if created)
- `.skillsaw-baseline.json` (if created)
- `.skillsaw-badge.json` and `README.md` (if the badge was set up)
- `.github/workflows/lint.yml` (if created)
- `.github/workflows/lint-review.yml` (if created)
- `.gitlab-ci.yml` (if modified)
- `Makefile` (if created or modified)
- Any files that were fixed
<!-- skillsaw-enable content-unlinked-internal-reference -->
