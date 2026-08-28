# ledger

A double-entry ledger. Every balance in the system is derived by replaying
entries, never stored — so an entry, once written, is immutable.

## The one rule that matters

Amounts are integers of minor units. A float anywhere in a money path is a
correctness bug, not a style preference: `0.1 + 0.2` does not equal `0.3`,
and a cent lost here is a cent that never reconciles.

Use `Money.fromMinor(1250)` for £12.50. `Money` refuses construction from a
float.

## Working here

| Task | Command |
| --- | --- |
| Install | `pnpm install` |
| Unit tests | `pnpm test` |
| Contract tests | `pnpm test:contract` |
| Format | `pnpm format` |

The contract suite talks to the sandbox settlement API. Copy `.env.example`
to `.env.local` and fill in `SANDBOX_KEY` before running it; without the key
it skips, which is easy to mistake for passing.

## Before you open a pull request

Run `pnpm format` — CI rejects unformatted code. Put one logical change in
each pull request, reference the issue key in the title (`LED-88: retry
settlement`), and add a `CHANGELOG.md` entry when the change is visible to
an integrator.
