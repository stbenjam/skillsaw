# AGENTS.md

Conventions for the `notifier` service.

## Build and test

- Install dependencies with `go mod download`.
- Run the unit suite with `go test ./...`.
- Run the race detector before opening a pull request: `go test -race ./...`.

## Code conventions

- Format with `gofmt -w .`. CI rejects unformatted code.
- Every exported function documents the errors it returns.
- Send through `notifier/transport`. Do not call the provider SDK directly.

## Pull requests

- One logical change per pull request.
- Reference the issue key in the title, e.g. `NOT-12: retry webhooks`.
