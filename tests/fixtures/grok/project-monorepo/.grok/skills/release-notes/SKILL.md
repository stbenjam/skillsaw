---
name: release-notes
description: Use when drafting the release notes for a workspace tag, so every crate bumped in the range is accounted for.
---

# Release notes

Turn the commit range for a tag into notes that name every crate that
moved.

## Steps

1. Run `git log --oneline $PREVIOUS..HEAD` for the range being released.
2. Run `cargo release changes` to list the crates whose versions moved.
3. Group the commits by crate. A commit touching no released crate goes
   under "Workspace".
4. Read `packages/*/CHANGELOG.md` for entries the commit subjects miss.

Every bumped crate must appear in the notes, even if only to say it was a
dependency bump.
