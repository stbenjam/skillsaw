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

## Step 1: Install skillsaw

Check if `skillsaw` is already available by running `skillsaw --version`. If it
is installed, skip to Step 2.

If not installed, choose the best method for this environment:

1. **uvx (preferred)** — zero-install, works immediately:
   ```
   uvx skillsaw
   ```
   Use `uvx skillsaw` as the command prefix for all subsequent steps (e.g.
   `uvx skillsaw tree`, `uvx skillsaw fix`).

2. **pip** — if uvx is not available:
   ```
   pip install skillsaw
   ```

3. **Container (podman or docker)** — if neither uvx nor pip is available.
   Use whichever runtime is installed (`podman` or `docker`):
   ```
   podman pull ghcr.io/stbenjam/skillsaw:latest
   podman run -v $(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw
   ```
   The `:Z` suffix relabels the mount for SELinux. Mount the repo at
   `/workspace` and pass subcommands after the image name
   (e.g. `podman run -v $(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw tree`).

Confirm the installation works by running `skillsaw --version` (or the
equivalent for the chosen method) before proceeding.

## Step 2: Initial scan

Run `skillsaw tree` to see what skillsaw detects in this repo — the repo type,
instruction files, plugins, skills, and other components. Show the user a brief
summary of what was found.

Then run `skillsaw` (lint) and capture the full output. Count the errors and
warnings. If the repo has zero violations, congratulate the user and skip to
Step 6 (config) or Step 7 (CI setup).

## Step 3: Apply deterministic autofixes

Run `skillsaw fix` to apply safe, deterministic fixes (e.g. adding missing
frontmatter, fixing names to kebab-case, registering unregistered plugins).

After fixing, run `skillsaw` again to see what remains. Report to the user:
- How many violations were auto-fixed
- How many violations remain

If all violations are resolved, skip to Step 6.

## Step 4: Fix remaining violations manually

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

## Step 5: Baseline remaining violations

If any violations remain after Steps 3–4, offer to create a baseline:

Tell the user: "There are N remaining violations. I can create a baseline file
(`.skillsaw-baseline.json`) so these are accepted for now — only *new*
violations will fail going forward. You can fix them over time and re-run
`skillsaw baseline` to shrink the accepted set."

If the user agrees, run `skillsaw baseline` and confirm the file was created.
Remind them to commit `.skillsaw-baseline.json` to the repository.

## Step 6: Generate configuration

If no `.skillsaw.yaml` exists yet, run `skillsaw init` to generate a default
config file. Tell the user they can customize rule settings in this file.

If one already exists, skip this step.

## Step 7: Set up CI

Ask the user which CI system they use. Offer the following options:

### GitHub Actions

Create `.github/workflows/lint.yml`:

Pin actions to commit SHAs for supply-chain protection. Look up the current
SHAs before creating the workflow:

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
      - uses: stbenjam/skillsaw/review@<SKILLSAW_SHA> # v0
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

## Step 8: Makefile targets

Ask the user if they want Makefile targets for running skillsaw locally. If
they decline, skip to Step 9.

First, look up the latest skillsaw version to pin against:

```
curl -s https://pypi.org/pypi/skillsaw/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"
```

If `curl` or `python3` is unavailable, fall back to:

```
git ls-remote --tags https://github.com/stbenjam/skillsaw.git 'v*' | sort -t/ -k3 -V | tail -1
```

Ask the user whether they prefer **uvx** or **podman/docker** for the targets.

### uvx targets

```makefile
SKILLSAW_VERSION := <LATEST_VERSION>

.PHONY: lint lint-fix
lint:
	uvx skillsaw==$(SKILLSAW_VERSION) --strict

lint-fix:
	uvx skillsaw==$(SKILLSAW_VERSION) fix
```

### podman/docker targets

Use whichever container runtime is installed. Pin to the version tag, not
`latest`:

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
either case, do not overwrite existing `lint` or `lint-fix` targets — if they
already exist, ask the user what names to use instead (e.g. `skillsaw-lint`).

## Step 9: README badge

Ask the user if they want a skillsaw grade badge in their README. The badge
shows the repository's letter grade (A+ through F) and updates whenever the
badge file is regenerated. If they decline, skip to Step 10.

If they agree:

1. Run `skillsaw badge`. This writes `.skillsaw-badge.json` to the repo root
   and prints ready-to-paste markdown for two shields.io badge styles.
2. Add the **endpoint badge** markdown (the variant whose color tracks the
   grade automatically) to `README.md`:
   - If the README already has badges (look for `img.shields.io`,
     `badge.svg`, or similar image links near the top), add the skillsaw
     badge on the same line or block as the existing badges.
   - If there are no badges yet, add it on its own line directly under the
     top-level heading.
3. The badge must link to `https://skillsaw.org/` — the markdown printed by
   `skillsaw badge` already does this; keep that link when placing it.
4. If `skillsaw badge` printed a URL placeholder (no GitHub remote detected),
   tell the user the badge will render once `.skillsaw-badge.json` is
   published at a URL shields.io can fetch, and leave the placeholder for
   them to fill in.

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

Tell the user the badge reflects the committed `.skillsaw-badge.json`, so it
should be regenerated when content changes — run `make lint` (or `skillsaw
badge` directly), or add it to CI (e.g. a workflow step that runs `skillsaw
badge` and commits the file if it changed). The badge ignores any baseline:
it always reflects the repository's true grade.

## Step 10: Final verification

Run `skillsaw` one final time and confirm the repo passes (exit 0). Summarize
what was done:

- Number of violations found initially
- Number fixed automatically
- Number fixed manually
- Number baselined
- CI setup (if any)
- Makefile targets (if any)
- README badge (if added)
- Files created or modified

Remind the user to commit all new/changed files:
- `.skillsaw.yaml` (if created)
- `.skillsaw-baseline.json` (if created)
- `.skillsaw-badge.json` and `README.md` (if the badge was set up)
- `.github/workflows/lint.yml` (if created)
- `.github/workflows/lint-review.yml` (if created)
- `.gitlab-ci.yml` (if modified)
- `Makefile` (if created or modified)
- Any files that were fixed
