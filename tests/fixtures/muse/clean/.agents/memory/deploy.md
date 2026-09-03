# Deploying the ledger

Migrations ship before the binary, always. The service reads the new columns
only behind the `ledger_v2_posting` flag, so a migration that lands ahead of
the deploy is inert, while a binary that lands ahead of its migration takes
posting down.

The order is:

1. Merge the migration on its own, wait for the nightly migration job.
2. Merge the code change. The deploy pipeline runs the canary for five
   minutes against 1% of traffic before it promotes.

The five-minute canary is not arbitrary — the posting reconciler runs on a
four-minute timer, so a shorter canary can promote a build that has never
reconciled once.

If the canary stalls in `Progressing`, the usual cause is a pod stuck
waiting on the Postgres connection pool. Page the on-call for `payments`
rather than rolling back by hand; the rollback needs the flag flipped first.
