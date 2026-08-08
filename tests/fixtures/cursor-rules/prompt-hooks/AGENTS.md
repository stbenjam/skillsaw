# Payments Service

A Go service that settles card authorizations against the ledger.

## Conventions

- Money is `int64` minor units. Never `float64`.
- Every handler takes a `context.Context` as its first argument.
- Run `make test` before pushing; it runs `go vet` too.
