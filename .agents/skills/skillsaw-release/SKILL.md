---
name: skillsaw-release
description: Bump the version, generate release notes, and publish a new skillsaw release to PyPI. Use when cutting a new release.
compatibility: Requires git, gh CLI, and internet access
user-invocable: true
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Release

You are releasing a new version of the **skillsaw** linter.

## Step 1: Pre-flight checks

Before releasing, verify:

1. You are on the `main` branch, it is clean (`git status`), and up to
   date with `origin/main` (`git pull origin main`)
2. All tests pass: `make test`
3. Formatting is clean: `make lint`
4. Determine what version to release — if no version was specified,
   choose based on the commits since the last tag: new features or rules
   → bump minor; fixes only → bump patch (the bump script defaults to
   patch when given no argument)

The Makefile automatically creates the `.venv` and installs dependencies.

## Step 2: Bump the version

Run the bump script:

```bash
.venv/bin/python -c "pass" || make venv
bash scripts/bump-version.sh [version]
```

This updates `pyproject.toml`, `src/skillsaw/__init__.py`, and
`action.yml` (the action's default skillsaw version). If no version
argument is given, it increments the patch version automatically.

Then regenerate generated files and catch the pinned version references
the script does NOT update:

```bash
make update
grep -rn "{old_version}" README.md docs/
```

Update every stale pin by hand — currently `pip install skillsaw==X.Y.Z`
in `README.md` and `docs/ci.md`, and pre-commit `rev: vX.Y.Z` in
`README.md` and `docs/pre-commit.md`. Do NOT touch historical
"Since vX.Y.Z" lines in `docs/rules/`.

## Step 3: Open a version-bump PR

`main` is branch-protected — a direct push is rejected, so the bump goes
through a PR. First verify remotes with `git remote -v` (`origin` should
be stbenjam/skillsaw). Then:

```bash
git checkout -b release/{version}-bump
git add -A
git commit -m "[Auto] Bump version to {version}"
git push -u origin release/{version}-bump
gh pr create --title "[Auto] Bump version to {version}" --body "Version bump for the {version} release."
```

Wait for all required checks to pass, merge the PR, then update local
main:

```bash
gh pr checks {pr} --watch
gh pr merge {pr} --squash
git checkout main && git pull origin main
```

## Step 4: Generate release notes

Get all commits since the last tag:

```bash
git log $(git describe --tags --abbrev=0)..HEAD --oneline --no-merges
```

Organize the commits into categories:

- **New features** — new rules, new functionality
- **Fixes** — bug fixes, validation corrections
- **Other** — refactoring, CI changes, docs

Write the release notes in markdown. Keep it concise — one line per change.
Include a "## What's New" header. Skip trivial commits (version bumps, merge
commits, CI-only changes).

## Step 5: Create the GitHub release

Only after the bump PR has merged, so the tag includes the bumped
version files:

```bash
gh release create v{version} --title "v{version}" --notes "{release_notes}" --target main
```

This triggers the `release.yml` workflow which builds and publishes to PyPI
via OIDC trusted publishing.

## Step 6: Verify the publish

Wait for the release workflow to complete:

```bash
gh run list --workflow release.yml --limit 1 --json status,conclusion
```

If the conclusion is `success`, the release is live on PyPI. If it failed,
investigate the workflow logs and report the error.
