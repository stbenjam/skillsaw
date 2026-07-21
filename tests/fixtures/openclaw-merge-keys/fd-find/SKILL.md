---
name: fd-find
description: Locate files and directories quickly with fd, a fast and user-friendly alternative to find. Use when you need to enumerate files by name, extension, or modification time.
metadata:
  defaults: &openclaw-defaults
    category: search
    emoji: "📁"
  openclaw:
    <<: *openclaw-defaults
    always: false
    requires:
      bins:
        - fd
---

# fd Find

Use `fd` to locate files by name. It honors `.gitignore`, uses smart case,
and defaults to the current directory.

## Common invocations

- `fd config` — find anything whose name contains "config"
- `fd -e md` — find all markdown files
- `fd -H dotfile` — include hidden files
- `fd --changed-within 1d` — files modified in the last day

## Tips

Combine with `xargs` or `-x` to run a command per result, e.g.
`fd -e py -x ruff check`.
