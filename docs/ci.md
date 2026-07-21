# CI Integration

## GitHub Action

The GitHub Action installs skillsaw, runs it, and prints violations in the CI
log. A separate review action posts violations as inline PR comments with
automatic deduplication and thread resolution.

### Basic usage (lint only)

```yaml
name: Lint

on: [pull_request]

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

### With PR review comments

To post inline comments on PRs (including fork PRs), use the two-workflow
pattern. The lint workflow runs with read-only permissions and uploads the
report as an artifact. A second workflow triggers on completion and posts
comments with write permissions — without ever checking out untrusted code.

```yaml
# .github/workflows/lint.yml
name: Lint

on:
  pull_request:
  push:
    branches: [main]

# SECURITY: This workflow runs on untrusted PR code, so it has read-only
# permissions. It cannot post comments — that's handled by lint-review.yml.
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

```yaml
# .github/workflows/lint-review.yml
name: Lint Review

# SECURITY: workflow_run triggers run in the context of the BASE branch (main),
# not the PR branch. This workflow never checks out or executes untrusted PR
# code — it only downloads the lint report artifact produced by the Lint
# workflow and posts review comments. This is GitHub's recommended pattern for
# safely granting write permissions to PR feedback workflows.
# See: https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#workflow_run
on:
  workflow_run:
    workflows: ["Lint"]
    types: [completed]

jobs:
  review:
    # Only run for pull requests, not push events.
    if: github.event.workflow_run.event == 'pull_request'
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      # Reads the lint report artifact from the Lint workflow and posts inline
      # PR comments. Does not run skillsaw or execute any PR code.
      - uses: stbenjam/skillsaw/review@v0
```

### Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `path` | Path to lint | `.` |
| `version` | Specific skillsaw version to install | latest |
| `strict` | Treat warnings as errors | `false` |
| `fail-on` | Fail on violations at this severity or above (`error`, `warning`, `info`); `strict: true` is equivalent to `fail-on: warning`, and combining `strict` with a contradictory `fail-on` fails the run | `''` |
| `verbose` | Include info-level violations | `false` |
| `no-custom-rules` | Skip custom rules defined in `.skillsaw.yaml` | `true` |
| `plugins` | Newline-separated list of plugin packages to install | `''` |

### Outputs

| Output | Description |
|--------|-------------|
| `exit-code` | skillsaw exit code (0=pass, 1=violations at or above the fail-on threshold) |
| `errors` | Number of errors found |
| `warnings` | Number of warnings found |
| `report-file` | Path to JSON report file |

### Supply Chain Protection

The examples above use `@v0` for brevity. For supply-chain protection,
replace `@v0` with a pinned commit SHA:

```yaml
- uses: stbenjam/skillsaw@d252498eb6260e197c9c395a650643d9c49ae37b # v0
```

While this project follows current best practices — PyPI trusted provenance,
2FA, signed releases — pinning to a SHA prevents a compromised tag from
injecting malicious code into your workflow. Find the current SHA for a
tag with:

```bash
git ls-remote --tags https://github.com/stbenjam/skillsaw.git v0
```

### PR comment behavior

- Each violation gets its own inline comment on the relevant line or file
- Comments are deduplicated across re-runs using content fingerprinting
- When a violation is fixed, its comment thread is automatically resolved
- Comments with human replies are preserved

## Badge and report card

`skillsaw badge` writes `.skillsaw-badge.json` (a shields.io endpoint
payload) and prints ready-to-paste README markdown. Add `--large` to also
render `.skillsaw-card.svg` — a self-contained SVG report card showing
the letter grade, weighted violation density, content-token count,
plugin/skill counts, and the top offending rules (`--theme light|dark`,
default dark):

![skillsaw's own report card, dark theme (the default)](https://raw.githubusercontent.com/stbenjam/skillsaw/main/.skillsaw-card.svg)

Regenerate both on pushes to your default branch and commit them when
they change:

```yaml
name: Badge

on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  badge:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - run: pipx install skillsaw
      - run: skillsaw badge --large .  # grades, never gates (always exits 0)
      - name: Commit badge artifacts
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .skillsaw-badge.json .skillsaw-card.svg
          git diff --cached --quiet || git commit -m "Update skillsaw badge"
          git push
```

Both images are served from your repository via
`raw.githubusercontent.com`. GitHub proxies README images through its
camo cache, which caches aggressively — a freshly regenerated badge or
card can appear stale for a while after pushing.

## Other output formats

skillsaw supports several machine-readable output formats — `--format`
(stdout) and `--output` (file) accept `text`, `json`, `sarif`, `html`,
`code-climate`, and `gitlab` — including [SARIF
2.1.0](https://sarifweb.azurewebsites.net/) for tools that ingest it.
See the [CLI reference](cli.md) for details.

## GitLab CI

For GitLab merge-request widgets, use the `gitlab` output format (a Code
Quality report, available since skillsaw 0.11.3):

```yaml
skillsaw:
  script:
    - pip install skillsaw==0.17.0
    - skillsaw lint --output gitlab:gl-code-quality-report.json .
  artifacts:
    reports:
      codequality: gl-code-quality-report.json
```
