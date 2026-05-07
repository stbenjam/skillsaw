---
name: skillsaw-release
description: Bump the version, generate release notes, and publish a new skillsaw release to PyPI. Use when cutting a new release.
compatibility: Requires git, gh CLI, and internet access
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Release

You are releasing a new version of the **skillsaw** linter.

## Step 1: Pre-flight checks

Before releasing, verify:

1. You are on the `main` branch and it is clean (`git status`)
2. All tests pass: `make test`
3. Formatting is clean: `make lint`
4. Determine what version to release — if no version was specified, the
   bump script will auto-increment the patch version

The Makefile automatically creates the `.venv` and installs dependencies.

## Step 2: Bump the version

Run the bump script:

```bash
.venv/bin/python -c "pass" || make venv
bash scripts/bump-version.sh [version]
```

This updates both `pyproject.toml` and `src/skillsaw/__init__.py`. If no
version argument is given, it increments the patch version automatically.

Verify the bump by checking the output and confirming both files were updated.

## Step 3: Commit and push the version bump

First verify remotes with `git remote -v` to confirm `origin` points to
the user's fork (stbenjam/skillsaw). Then:

```bash
git add pyproject.toml src/skillsaw/__init__.py
git commit -m "[Auto] Bump version to {version}"
git push origin main
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

```bash
gh release create v{version} --title "v{version}" --notes "{release_notes}"
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
