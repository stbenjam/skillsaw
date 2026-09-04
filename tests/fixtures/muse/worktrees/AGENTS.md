# Search indexer

Builds the product search index from the catalog stream. Rust, Tantivy, and
a Kafka consumer that reads `catalog.v2`.

## Build and test

- `cargo test` runs the unit suite.
- `cargo run --bin backfill` rebuilds the index from a catalog snapshot.

## Conventions

- Index schema changes need a backfill plan in the PR description.
- Never change the analyzer without reindexing; a mixed index scores badly.
