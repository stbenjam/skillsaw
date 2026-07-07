---
name: skillsaw-release
description: Bump the version, generate release notes, and publish a new skillsaw release to PyPI. Use when cutting a new release.
compatibility: Requires git, gh CLI, and internet access
license: Apache-2.0
user-invocable: true
metadata:
  author: stbenjam
  version: "1.0"
---

<!-- Source paths below are repo-root-relative references, not links navigable from this skill's directory. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

# skillsaw Release

Follow these steps to release a new version of the **skillsaw** linter.

## Step 1: Run pre-flight checks

Before releasing, verify:

1. Check you are on the `main` branch, it is clean (`git status`), and up to
   date with `origin/main` (`git pull origin main`).
2. All tests pass: `make test`.
3. Formatting is clean: `make lint`.
4. Determine which version to release. If none was specified, review the
   commits since the last tag. Add a minor bump for new features or rules;
   keep a patch bump for fixes only (the bump script defaults to patch when given no argument).

The Makefile creates the `.venv` and installs dependencies automatically; run `make venv` first if needed.

## Step 2: Run the bump script

Run the bump script:

```bash
.venv/bin/python -c "pass" || make venv
bash scripts/bump-version.sh [version]
```

Verify the script updated `pyproject.toml`, `src/skillsaw/__init__.py`, and
`action.yml` (the action's default skillsaw version). If you pass no version
argument, keep it empty — the script increments the patch version automatically.

Then run `make update` to regenerate generated files and catch the pinned
version references the script does NOT update:

```bash
make update
grep -rn "{old_version}" README.md docs/
```

Update every stale pin by hand — currently `pip install skillsaw==X.Y.Z` in
`README.md` and `docs/ci.md`, and the pre-commit `rev: vX.Y.Z` in `README.md`
and `docs/pre-commit.md`. Never touch historical "Since vX.Y.Z" lines in `docs/rules/`.

## Step 3: Create a version-bump PR

`main` is branch-protected — a direct push is rejected, so the bump goes
through a PR. First verify remotes with `git remote -v` (`origin` should
be stbenjam/skillsaw). Then run:

```bash
git checkout -b release/{version}-bump
git add -A
git commit -m "[Auto] Bump version to {version}"
git push -u origin release/{version}-bump
gh pr create --title "[Auto] Bump version to {version}" --body "Version bump for the {version} release."
```

Wait for all required checks to pass, merge the PR, then update local main:

```bash
gh pr checks {pr} --watch
gh pr merge {pr} --squash
git checkout main && git pull origin main
```

## Step 4: Write the release notes

Read all commits since the last tag with `git log`:

```bash
git log $(git describe --tags --abbrev=0)..HEAD --oneline --no-merges
```

Review the commits and group them into categories:

- **New features** — new rules, new functionality.
- **Fixes** — bug fixes, validation corrections.
- **Other** — refactoring, CI changes, docs.

Write the release notes in markdown. Keep it concise — one line per change.
Include a "## What's New" header. Skip trivial commits (version bumps, merge commits, CI-only changes).

## Step 5: Create the GitHub release

Create the release only after the bump PR has merged, so the tag includes the bumped version files:

```bash
gh release create v{version} --title "v{version}" --notes "{release_notes}" --target main
```

The tag triggers the `release.yml` workflow to build and publish to PyPI via OIDC trusted publishing.

## Step 6: Verify the publish

Check the release workflow completes:

```bash
gh run list --workflow release.yml --limit 1 --json status,conclusion
```

Check the conclusion: if `success`, the release is live on PyPI. If it failed,
review the workflow logs and report the error.
