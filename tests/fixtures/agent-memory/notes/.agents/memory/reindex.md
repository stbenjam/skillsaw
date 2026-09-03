# Reindexing the catalog

A full reindex runs in two passes. The first writes every document into a
new index with refresh disabled; the second re-enables refresh and replays
the change log accumulated during the first pass.

Skipping the second pass leaves the new index missing every write that
landed while the first pass ran, which is typically twenty minutes of
catalog edits. Nothing errors — the index is simply stale, and the staleness
only shows up as customer reports of missing products days later.

The alias swap is the last step and is atomic. Readers never see a partial
index because they only ever query the `catalog-current` alias, which points
at the old index until the swap.
