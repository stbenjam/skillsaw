---
name:
  []
description: Skill whose name value is an empty flow sequence on the next line
---

# Multiline Name Skill

This skill's `name:` key holds a falsy value that lives on the following
line. The fix must replace the whole value span in place — replacing only
the key line would orphan the continuation and corrupt the frontmatter.
