# Update version pins

Change only pins that reference skillsaw; leave third-party actions and
unrelated tooling untouched. Track each edited file for the final summary.

## GitHub Actions and action definitions

Search repository-wide for workflows and action definitions referencing
skillsaw:

```console
grep -rnE "stbenjam/skillsaw(@|/review@)" .
```

This covers both the lint action (`stbenjam/skillsaw@<SHA>`) and the review
action (`stbenjam/skillsaw/review@<SHA>`).

For GitHub Actions workflows (`.github/workflows/*.yml`), resolve the commit
SHA of the newest release tag before editing:

```console
git ls-remote https://github.com/stbenjam/skillsaw.git 'refs/tags/v{latest}' 'refs/tags/v{latest}^{}'
```

The exact refs keep `v{latest}-rc1` and `v{latest}0` out of the answer. An
annotated tag yields two lines; use the SHA on the `^{}` line, which is the
commit the tag points to. Replace the old SHA with it and refresh the
trailing version comment to `# v{latest}`:

```yaml
- uses: stbenjam/skillsaw@<NEW_SHA> # v{latest}
```

Or for the review action:

```yaml
- uses: stbenjam/skillsaw/review@<NEW_SHA> # v{latest}
```

If the repository defines its own actions, check every action metadata file
for a skillsaw version input with a pinned default:

```console
grep -rn -B3 "default: '[0-9]" --include=action.yml --include=action.yaml . | grep -iA3 skillsaw
```

Update that input's `default: '{old}'` to `default: '{latest}'`; leave other
inputs' defaults alone.

## Makefile targets

Find the pinned version:

```console
grep -n "SKILLSAW_VERSION" Makefile
```

Update the version value while preserving the existing assignment operator
(e.g. `SKILLSAW_VERSION := {latest}` or `SKILLSAW_VERSION ?= {latest}`).
When the targets run through a container, the image tag below it references
the same variable (`ghcr.io/stbenjam/skillsaw:v$(SKILLSAW_VERSION)`), so one edit
covers both. Never overwrite existing `lint` or `lint-fix` target bodies; only
the version assignment changes.

## Pre-commit hooks

Find the skillsaw entry in `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/stbenjam/skillsaw
    rev: v{latest}
    hooks:
      - id: skillsaw
```

Set `rev:` to the `v{latest}` tag. Tags are the pre-commit convention here;
a full commit SHA also works when the project prefers immutable pins.

## Container image tags and Dockerfiles

Search repository-wide for container image pins, including nested Dockerfiles,
Containerfiles, and GitLab CI configurations:

```console
grep -rn "ghcr.io/stbenjam/skillsaw" . 2>/dev/null
```

Retag `:v{old}` to `:v{latest}` in every file the search found: Dockerfiles,
Containerfiles, `.gitlab-ci.yml`, and any GitLab CI file it includes. A `:latest` tag floats onto the new release
by itself; recommend pinning it to `:v{latest}` for repeatable pipelines,
but only change it after the user agrees.

Return to the router with the list of edited files.
