# AGENTS.md

Conventions for the `search-indexer` service.

## Build and test

- Install dependencies with `cargo fetch`.
- Run the unit suite with `cargo test`.
- Run the index rebuild benchmark with `cargo bench --bench rebuild` before
  changing any tokenizer.

## Code conventions

- Format with `cargo fmt`. CI rejects unformatted code.
- Every public function documents the errors it returns.
- Index writes go through `indexer::writer`. Do not open a segment directly.

## Pull requests

- One logical change per pull request.
- Reference the issue key in the title, e.g. `IDX-9: shard by tenant`.
