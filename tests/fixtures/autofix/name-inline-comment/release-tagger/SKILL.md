---
name: "release#tagger" # hash is part of the quoted value, not a comment
description: Use this skill when tagging a release for the deployment pipeline
---

# Release Tagger

Tags the current commit with the next release version and pushes the tag to
the shared remote so the deployment pipeline can pick it up.
