# Project Standards

This service exposes a REST API for order management. Use these instructions
when making changes.

## Build and test

- Build with `make build`; run unit tests with `make test`.
- Run `make integration` before opening a pull request. It starts a local
  postgres container and requires podman or docker.

## Code conventions

- Handlers live in `internal/api/`; one file per resource.
- Database access goes through the repository layer in `internal/store/` —
  handlers never issue SQL directly.
- WIP: document the retry policy for outbound webhook calls.

## Error handling

Return typed errors from the store layer. Handlers map them to HTTP status
codes in `internal/api/errors.go`; never map status codes inside the store.
