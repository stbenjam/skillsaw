---
name: release
description: Cut a sprocketd release. Use when publishing a new version tag.
---

# Release

1. Bump the version in the manifest and regenerate the changelog.
2. Follow [references/checklist.md](references/checklist.md) for the
   stage-by-stage procedure, including the signing steps.
3. Tag the release and push the tag; CI builds and publishes from the
   tag, never from a branch head.
4. Announce in the release channel once the publish job goes green.

The checklist is the source of truth for ordering — when this file and
the checklist disagree, the checklist wins. Keep this file short and
put any new procedure detail in the checklist instead. If the publish
job fails after the tag is pushed, do not delete the tag; fix forward
with a patch release, because downstream mirrors pick up tags within
minutes and a deleted tag leaves them permanently out of sync.
