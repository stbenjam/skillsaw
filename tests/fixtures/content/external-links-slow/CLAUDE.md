# Ledger archive

The archive holds settled batches older than 90 days. It is read-only: new
batches land in the live ledger and migrate here once they are closed.

## Reference material

Both services below run on the batch cluster, which answers slowly while a
nightly job is in flight.

- [Archive query API](http://127.0.0.1:__PORT__/slow) — read a settled batch
  by id.
- [Archive index](http://127.0.0.1:__PORT__/slow-index) — the batch id to
  storage-partition mapping.

## Restoring a batch

1. Locate the batch id in the archive index.
2. Request a restore through the finance data team.
3. Confirm the restored batch balances before using it in a reconciliation.

Stop once the restored batch balances; do not re-run the nightly pipeline
against archived data.
