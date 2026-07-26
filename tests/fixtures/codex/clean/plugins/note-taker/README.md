# note-taker

Capture decisions from a Codex session into a dated note file, and pull
them back into context when you return to the same work.

## Install

```
codex plugin install note-taker
```

## What it adds

| Surface | Name | Purpose |
|---|---|---|
| Command | `/capture` | Append a summary of the current exchange to today's note |
| Skill | `capture-notes` | Decide what is worth writing down, and in whose words |

Notes live in `notes/YYYY-MM-DD.md` relative to the repository root. The
plugin only appends; it never rewrites an entry that is already there.
