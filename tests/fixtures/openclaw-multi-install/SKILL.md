---
name: openclaw-multi-install
description: Search the repository with ripgrep, installed per-platform via node or Homebrew. Use when you need fast text search across the working tree.
metadata:
  openclaw:
    os:
      - windows
    install:
      - id: node-install
        kind: node
      - id: brew-install
        kind: brew
        formula: ripgrep
        os:
          - linux
---

# Multi-install Search

Use `rg` to search the working tree quickly. The skill installs ripgrep
through the installer matching your platform.

## Common invocations

- `rg 'pattern'` — search all tracked text files
- `rg -n 'pattern' src/` — include line numbers, limit to a directory
