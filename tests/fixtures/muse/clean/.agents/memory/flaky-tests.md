# Flaky tests

Three integration tests fail intermittently. None of them indicate a real
regression on their own — check the cause here before you start bisecting.

`TestReconcilerCatchUp` fails roughly once in forty runs. The reconciler
timer and the test's fixed clock advance in different goroutines, so a slow
CI worker can observe the pre-advance value. Tracked in LEDGER-2291.

`TestMigrationRollback` fails whenever Docker hands the suite a Postgres
container that is still replaying WAL. The suite waits for the health check
but not for `pg_isready`, so the first connection can land during recovery.
Tracked in LEDGER-2044.

`TestAPIRateLimit` fails on the shared runners only. The limiter measures
wall-clock time and the runners oversubscribe CPU badly enough that a
100ms window can take 140ms. It has never failed on a dedicated runner.

If one of these fails, re-run the job once. If it fails twice in a row, it
is not the known flake — investigate it.
