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
| `verbose` | Include info-level violations | `false` |

### Outputs

| Output | Description |
|--------|-------------|
| `exit-code` | skillsaw exit code (0=pass, 1=errors, 2=strict+warnings) |
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
