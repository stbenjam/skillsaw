# Update version pins

Change only pins that reference skillsaw; leave third-party actions and
unrelated tooling untouched. `{old}` below is the version a pin currently
carries, which may differ from `{installed}`. Search tracked files with
`git grep` so vendored trees, build output and the skill's own mirrored
copies stay out of the answer. Track each edited file for the final summary.

## GitHub Actions and action definitions

Find every workflow and action definition referencing skillsaw:

```console
git grep -nE "stbenjam/skillsaw(@|/review@)"
```

This covers both the lint action (`stbenjam/skillsaw@<SHA>`) and the review
action (`stbenjam/skillsaw/review@<SHA>`), in `.yml` and `.yaml` workflows
and in action metadata alike.

Resolve the commit SHA of the newest release tag before editing:

```console
git ls-remote https://github.com/stbenjam/skillsaw.git 'refs/tags/v{latest}' 'refs/tags/v{latest}^{}'
```

An annotated tag yields two lines; use the SHA on the `^{}` line, which is
the commit the tag points to. A lightweight tag yields one line, and its SHA
is the commit. Replace the old SHA in every `uses:` line the search found and
refresh the trailing version comment to `# v{latest}`:

```yaml
- uses: stbenjam/skillsaw@<NEW_SHA> # v{latest}
```

Or for the review action:

```yaml
- uses: stbenjam/skillsaw/review@<NEW_SHA> # v{latest}
```

A step that also passes `with: version: {old}` to the action gets `{latest}`
there too; a bumped SHA beside a stale version input is worse than neither.

If the repository defines its own actions, find the skillsaw version input in
each action metadata file and its default, whatever the quoting:

```console
git grep -n -iA4 skillsaw -- 'action.yml' 'action.yaml' '**/action.yml' '**/action.yaml' | grep -E 'default: *["'"'"']?v?[0-9]'
```

Update that input's default from `{old}` to `{latest}`, keeping the quoting
and `v` prefix the file already uses; leave other inputs' defaults alone.

## Makefile targets

Find the pinned version:

```console
git grep -n "SKILLSAW_VERSION" -- Makefile '**/Makefile'
```

Update the version value while preserving the existing assignment operator
(`SKILLSAW_VERSION := {latest}` or `SKILLSAW_VERSION ?= {latest}`). When the
targets run through a container, the image tag below it references the same
variable (`ghcr.io/stbenjam/skillsaw:$(SKILLSAW_VERSION)`), so one edit covers
both. Never overwrite existing `lint` or `lint-fix` target bodies; only the
version assignment changes.

## Pre-commit hooks

Find the skillsaw entry:

```console
git grep -n -A3 "stbenjam/skillsaw" -- .pre-commit-config.yaml
```

```yaml
repos:
  - repo: https://github.com/stbenjam/skillsaw
    rev: v{latest}
    hooks:
      - id: skillsaw
```

Set `rev:` to the `v{latest}` tag; git tags do carry the `v`. When the project
pins `rev:` to a commit SHA instead, resolve `v{latest}` the way the Actions
section does and use that SHA.

## Container image tags and Dockerfiles

Find every image reference, including nested Dockerfiles, Containerfiles and
GitLab CI configurations:

```console
git grep -n "ghcr.io/stbenjam/skillsaw"
```

Retag `:{old}` to `:{latest}` in every file the search found: Dockerfiles,
Containerfiles, `.gitlab-ci.yml` and any GitLab CI file it includes. Image
tags carry no `v`. When the tag is indirect (`:$(SKILLSAW_VERSION)`,
`:${SKILLSAW_VERSION}`, or a `FROM` built from an `ARG`), update the variable
or build argument it reads instead. A `:latest` tag floats onto the new
release by itself; recommend pinning it to `:{latest}` for repeatable
pipelines, but only change it after the user agrees.

## PyPI pins

Find pip-style pins in requirements files, `pyproject.toml`, `tox.ini`,
Dockerfiles and CI configurations:

```console
git grep -nE "skillsaw(==|@)[0-9]"
```

Bump each to `{latest}`, keeping the operator the file uses.

Return to the router with the list of edited files.
