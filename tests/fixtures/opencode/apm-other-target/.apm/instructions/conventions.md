# Warehouse conventions

APM compiles these into `.claude/` only — `targets:` lists `claude` and
nothing else, so the `.opencode/` directory beside it is hand-written.

## Build and test

- Install dependencies with `pnpm install`.
- Run the unit suite with `pnpm test`.
- Run the picking simulation with `pnpm test:sim` before changing any
  routing heuristic.

## Code conventions

- Format with `pnpm format`. CI rejects unformatted code.
- Bin coordinates are integers. Never round a float into one.
