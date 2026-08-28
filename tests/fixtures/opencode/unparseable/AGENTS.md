# notifier

Delivers webhooks and email. The service is at-least-once: a receiver may
see the same notification twice, and every payload carries an
`idempotency_key` so it can tell.

## Layout

- `transport/` — one file per provider. Nothing outside this package may
  import a provider SDK.
- `queue/` — retry and backoff. Retries are capped at six attempts over
  roughly an hour.
- `render/` — templates. Text and HTML bodies are rendered from the same
  source.

## Commands

Fetch dependencies with `go mod download`. Run `go test ./...` for the unit
suite and `go test -race ./...` before opening a pull request — the queue
package is concurrent and the race detector has caught real bugs in it.

`gofmt -w .` before committing; CI rejects unformatted code.

## Errors

Every exported function documents the errors it returns, because callers
branch on them: `ErrRetryable` goes back on the queue, anything else is
dead-lettered. Returning a bare `fmt.Errorf` from a transport therefore
sends a recoverable failure to the dead-letter queue.

Reference the issue key in the pull request title, e.g. `NOT-12: retry
webhooks`.
