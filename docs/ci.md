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
      - uses: actions/checkout@v5
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

### PR comment behavior

- Each violation gets its own inline comment on the relevant line or file
- Comments are deduplicated across re-runs using content fingerprinting
- When a violation is fixed, its comment thread is automatically resolved
- Comments with human replies are preserved
