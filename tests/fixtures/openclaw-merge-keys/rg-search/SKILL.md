---
name: rg-search
description: Search the repository fast with ripgrep, honoring gitignore rules and skipping binary files. Use when you need to find code patterns, symbols, or text across many files.
metadata:
  openclaw:
    emoji: "🔍"
    install:
      - &rg-base
        kind: brew
        formula: ripgrep
        bins:
          - rg
        os:
          - darwin
      - <<: *rg-base
        id: rg-linux
        os:
          - linux
---

# Ripgrep Search

Use `rg` to search the working tree. It respects `.gitignore` by default and
is dramatically faster than `grep -r`.

## Common invocations

- `rg 'pattern'` — search all tracked text files
- `rg -n 'pattern' src/` — include line numbers, limit to a directory
- `rg -t py 'def main'` — restrict to a file type
- `rg -l 'TODO'` — list matching files only

## Tips

Quote patterns to keep the shell from expanding them. Use `-F` for fixed
strings when the pattern contains regex metacharacters.
