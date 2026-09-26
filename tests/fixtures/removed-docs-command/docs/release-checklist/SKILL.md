---
name: release-checklist
description: Walk through the release checklist before tagging a new version. Use when preparing a release or reviewing a release pull request.
---

# Release checklist

Work through each step in order and stop at the first failure.

1. Confirm the changelog entry for the new version lists every merged pull request.
2. Run `make test` and `make lint`; both must pass on the release branch.
3. Bump the version in `pyproject.toml` and commit it with the changelog.
4. Tag the release commit and push the tag to trigger the publish workflow.

If the publish workflow fails, delete the tag, fix the cause, and start again from step 2.
