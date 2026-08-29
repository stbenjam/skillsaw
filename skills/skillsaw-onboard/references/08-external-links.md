# Set up external link checking

External URL availability is outside skillsaw's deterministic lint scope. Use
the dedicated [Lychee Action](https://github.com/lycheeverse/lychee-action) on
a schedule instead of making third-party availability a pull-request gate.

## GitHub Actions

Resolve current commit SHAs:

```console
git ls-remote --tags https://github.com/actions/checkout.git v5
git ls-remote --tags https://github.com/lycheeverse/lychee-action.git v2
```

Create `.github/workflows/link-check.yml` with those SHAs:

```yaml
name: Link Check

on:
  workflow_dispatch:
  schedule:
    - cron: '17 7 * * 1'

permissions:
  contents: read

concurrency:
  group: link-check
  cancel-in-progress: false

jobs:
  links:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@<CHECKOUT_SHA> # v5
        with:
          persist-credentials: false
      - uses: lycheeverse/lychee-action@<LYCHEE_SHA> # v2
        with:
          args: >-
            --no-progress
            --exclude-all-private
            --root-dir .
            './**/*.md'
          fail: true
          jobSummary: true
```

Record the workflow path, then return to the router.
