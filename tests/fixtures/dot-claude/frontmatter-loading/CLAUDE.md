# Payments service

Go service that settles card payments. Run `make test` before every commit
and `make lint` before opening a pull request.

## Layout

- `cmd/settle/` is the entry point.
- `internal/ledger/` owns double-entry bookkeeping; never write to it from handlers.
- `internal/gateway/` wraps the card network clients.

## Conventions

- Wrap errors with `fmt.Errorf("...: %w", err)`.
- Money is `int64` minor units; never use floats.
