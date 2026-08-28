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

The review action assumes its token posts as `github-actions[bot]`. When using
a GitHub App or PAT, set `comment-author` to that token's login so subsequent
runs can update and remove only the comments they own:

```yaml
- uses: stbenjam/skillsaw/review@v0
  with:
    token: ${{ secrets.REVIEW_APP_TOKEN }}
    comment-author: skillsaw-reviewer[bot]
```

### Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `path` | Path to lint | `.` |
| `version` | Specific skillsaw version to install | `0.20.0` |
| `strict` | Treat warnings as errors | `false` |
| `fail-on` | Fail on violations at this severity or above (`error`, `warning`, `info`); `strict: true` is equivalent to `fail-on: warning`, and combining `strict` with a contradictory `fail-on` fails the run | `''` |
| `verbose` | Include info-level violations | `false` |
| `no-custom-rules` | Skip custom rules defined in `.skillsaw.yaml` | `true` |
| `no-network` | Skip rules that make outbound network requests, whatever the linted repository enables | `true` |
| `plugins` | Trusted newline-separated pip requirements to install as rule plugins; values can select indexes or URLs | `''` |

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
- Comments are deduplicated across re-runs using fingerprints that include
  the source line. Upgrading from an older action may repost existing comments
  once as the new fingerprints take effect.
- When a violation is fixed, its unreplied review comment is deleted
- Comments with human replies are preserved

The repository's privileged PR follow-up agent does not reply to or resolve
inline review threads directly. It posts at most one PR-level summary naming
the inline comments it handled, leaving thread resolution to a collaborator.

## Badge and report card

`skillsaw badge` writes `.skillsaw-badge.json` (a shields.io endpoint
payload) and prints ready-to-paste README markdown. Add `--large` to also
render `.skillsaw-card.svg` — a self-contained SVG card with the repository
name and letter grade (`--theme light|dark`, default dark):

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

## Scheduled external link checking

A skillsaw run is offline by default — no rule opens a network connection
unless you turn one on. The only rule that does,
[`content-broken-external-reference`](rules/content-broken-external-reference.md),
requests every external `http(s)` link in your context files and reports
the ones the server says are gone (`404` and `410` only — never a bot
wall, a rate limit, or a timeout).

Keep it out of your pull-request job, where a slow origin would block a
merge, and give it a schedule of its own:

```yaml
name: link-check
on:
  schedule:
    - cron: "0 6 * * 1"   # Mondays, 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  links:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          persist-credentials: false
      - run: pipx install skillsaw
      - run: skillsaw lint . --rule content-broken-external-reference --strict -v
```

`--strict` is load-bearing. The rule reports at `warning`, and the default
threshold is `fail-on: error` — without it the job stays green even when it
finds dead links, and a scheduled job whose output nobody reads is only
useful if it can go red. `-v` surfaces the info-level notice that says the
network budget ran out before every link was checked.

Using `--rule` rather than `.skillsaw.yaml` keeps the rule out of every
other run, including local ones, and keeps your `skillsaw badge` grade
independent of whether a third-party URL 404s today.

A clean run is not proof every link resolved: bot walls, rate limits, 5xx
responses, timeouts and DNS failures are all treated as inconclusive and
reported nowhere.

The recipe above runs the CLI directly rather than the `skillsaw` Action,
because the Action has no per-rule selector today — no `rule`, `skip-rule`
or `args` input — and enabling the rule the only other way, in
`.skillsaw.yaml`, is what the section above tells you not to do. Use the
Action for your pull-request job and the CLI for this one.

### Refusing network access outright

`--no-network` (or `SKILLSAW_NO_NETWORK=1`) drops every rule that makes
outbound requests, on `lint`, `fix`, `baseline`, and `badge` — regardless
of what the linted repository's `.skillsaw.yaml` enables or what `--rule`
asks for. The linted repository is untrusted content, so the guarantee has
to belong to the operator:

```yaml
      - run: skillsaw lint . --no-network
```

The `skillsaw` Action sets it by default (`no-network: 'true'`); pass
`no-network: false` — the literal string, since anything else keeps the
network off — to opt a scheduled job back in. `fix` never runs a network
rule whatever the flag says: a dead URL has no mechanical fix, and the
autofix loop re-runs every rule's `check()` once per pass.

Naming only network rules while the gate is on — `--rule
content-broken-external-reference --no-network`, which is what an
org-wide `SKILLSAW_NO_NETWORK` export does to the scheduled job above — is
an error, not a green run over an empty rule set.

The companion control is `--allow-private-hosts`
(`SKILLSAW_ALLOW_PRIVATE_HOSTS=1`), which lets link checking reach
loopback, private and link-local addresses. It is off unless the operator
asks, and there is no `.skillsaw.yaml` key for it: a linted repository
that could grant it could point the runner at its own internal network.
Leave it off unless you are deliberately checking intranet links from a
trusted checkout.

## Other output formats

skillsaw supports several machine-readable output formats — `--format`
(stdout) and `--output` (file) accept `text`, `json`, `sarif`, `html`,
`code-climate`, and `gitlab` — including [SARIF
2.1.0](https://sarifweb.azurewebsites.net/) for tools that ingest it.
See the [CLI reference](cli.md) for details.

## Committed generated docs

Some repositories commit the output of `skillsaw docs` and gate CI on it
being current — regenerating in CI and failing if the working tree changed.
Upgrading skillsaw can change that output, so plan on regenerating and
committing the result as part of a version bump.

!!! note "Changed in 0.18"
    `skillsaw docs` output changed for every repository, Claude-only ones
    included. The generated HTML now escapes JavaScript-string contexts with
    a dedicated escaper (`escJsAttr`) and attribute contexts with `escAttr`,
    and plugin pages carry the manifest's `author` field. A repository that
    commits generated docs will see a diff on the first run under 0.18 and
    must regenerate; nothing about the published pages' behavior changes
    otherwise.

## GitLab CI

For GitLab merge-request widgets, use the `gitlab` output format (a Code
Quality report, available since skillsaw 0.11.3):

```yaml
skillsaw:
  script:
    - pip install skillsaw==0.20.0
    - skillsaw lint --output gitlab:gl-code-quality-report.json .
  artifacts:
    reports:
      codequality: gl-code-quality-report.json
```
