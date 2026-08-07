# payments-service

Go service that processes ledger transfers. Business logic lives in
`internal/ledger`; HTTP handlers are thin wrappers that only translate
between wire types and ledger calls.

## Gotchas

- Amounts are fixed-point int64 cents. Never convert through float64 —
  the ledger property tests will catch it.
- The audit row insert and the balance update must share one transaction;
  splitting them breaks idempotent replay on request-ID retries.
- Clean up temp files after tests if possible.

## Verification

Run `make test` before every push.

## Releases

Tag releases from the `release` branch only.

Run `make test` before every push.

## Pull requests

After opening a PR, keep monitoring for reviewer feedback and address
comments as they arrive.
