# search-indexer

A Rust service that maintains the tenant search index. Two processes share
one on-disk format: `indexerd` writes segments, `searchd` reads them.

## Index invariants

These hold at every commit point. Breaking one corrupts a live index, and
the failure surfaces hours later as missing results rather than as a crash.

| Invariant | Enforced by | What breaks if it slips |
| --- | --- | --- |
| Segment ids increase monotonically per shard | `writer::allocate_id` | Readers skip a segment and lose documents |
| A segment is fsynced before its manifest entry | `writer::commit` | A crash leaves a manifest pointing at nothing |
| Deletes are tombstones, never in-place edits | `writer::delete` | Concurrent readers see a torn document |
| One writer per shard, held by a lock file | `shard::lock` | Two writers interleave segment ids |

## Working on the tokenizer

The tokenizer is the one component with no backward-compatibility escape
hatch: a change to it means every existing segment tokenizes differently
from every new one. Before touching `tokenize/`, run
`cargo bench --bench rebuild` and record the numbers in the pull request.
A change that cannot be expressed as a new tokenizer *version* — leaving the
old one readable — needs a full reindex, which is an operations decision
rather than a code review one.

## Everything else

Dependencies: `cargo fetch`. Tests: `cargo test`. Formatting: `cargo fmt`.
Index writes go through `indexer::writer`; opening a segment directly
bypasses the lock. Title a pull request `IDX-9: shard by tenant`.
