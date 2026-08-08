# Release workflow

Cut a release from `main`.

## Steps

1. Confirm CI is green on the commit being tagged.
2. Bump the version in `pyproject.toml`.
3. Tag the commit and push the tag.
4. Stop and report if the tag already exists on the remote.

<!-- skillsaw-assert content-weak-language -->
Try to publish within an hour of tagging.
