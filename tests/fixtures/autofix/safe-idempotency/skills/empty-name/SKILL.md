---
name: ""
description: Skill whose name key exists but holds an empty string
---

# Empty Name Skill

This skill has a `name:` key with an empty value. The fix must replace the
value in place — prepending a second `name:` key corrupts the frontmatter.
