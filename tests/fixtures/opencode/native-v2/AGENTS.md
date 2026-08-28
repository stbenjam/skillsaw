# AGENTS.md

Conventions for the `ledger` service, running on OpenCode 2.0.

## Build and test

- Install dependencies with `pnpm install`.
- Run the unit suite with `pnpm test`.
- Run the contract tests with `pnpm test:contract`. They need the sandbox
  API key in `.env.local`; copy `.env.example` and fill it in.

## Code conventions

- Format with `pnpm format`. CI rejects unformatted code.
- Amounts are integers of minor units. Never use a floating-point type for
  money.
- Every exported function has an explicit return type.

## Pull requests

- One logical change per pull request.
- Reference the issue key in the title, e.g. `LED-88: retry settlement`.
- Update `CHANGELOG.md` when the change is user-visible.
