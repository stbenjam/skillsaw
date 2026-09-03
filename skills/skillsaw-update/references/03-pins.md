# Update version pins

Change only pins that reference skillsaw; leave third-party actions and
unrelated tooling untouched. Track each edited file for the final summary.

## GitHub Actions

Find workflows using the skillsaw action:

```console
grep -rn "stbenjam/skillsaw@" .github/workflows/
```

This covers both the lint action (`stbenjam/skillsaw@<SHA>`) and the review
action (`stbenjam/skillsaw/review@<SHA>`). Resolve the commit SHA of the
newest release tag before editing:

```console
git ls-remote --tags https://github.com/stbenjam/skillsaw.git 'v{latest}'
```

An annotated tag yields two lines; use the SHA on the `^{}` line, which is
the commit the tag points to. Replace the old SHA with it and refresh the
trailing version comment to `# v{latest}`:

```yaml
- uses: stbenjam/skillsaw@<NEW_SHA> # v{latest}
```

## Makefile targets

Find the pinned version:

```console
grep -n "SKILLSAW_VERSION" Makefile
```

Set `SKILLSAW_VERSION := {latest}`. When the targets run through a container,
the image tag below it references the same variable
(`ghcr.io/stbenjam/skillsaw:v$(SKILLSAW_VERSION)`), so one edit covers both.
Never overwrite existing `lint` or `lint-fix` target bodies; only the version
assignment changes.

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

## Container image tags

A GitLab job or Dockerfile may reference the published image directly:

```console
grep -rn "ghcr.io/stbenjam/skillsaw" .gitlab-ci.yml Dockerfile* 2>/dev/null
```

Retag `:v{old}` to `:v{latest}`. A `:latest` tag floats onto the new release
by itself; recommend pinning it to `:v{latest}` for repeatable pipelines,
but only change it after the user agrees.

Return to the router with the list of edited files.
