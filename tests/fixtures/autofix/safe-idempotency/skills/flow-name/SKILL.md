---
metadata: {tags: [legacy],
name: legacy-tag}
description: Skill whose only name lives inside a flow-mapping continuation line
---

# Flow Name Skill

The `name: legacy-tag}` line is a column-0 continuation of the `metadata`
flow mapping, not a top-level key. The fix must not splice that line (it
would destroy the closing brace); it must insert a real top-level name
instead.
