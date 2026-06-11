# Project Standards

## Build

Run `make build` to compile the project. The build uses vendored
dependencies, so run `go mod vendor` after changing `go.mod`.

## Testing

Run `make test` before pushing. Integration tests live under
`tests/integration/` and require the local database container.

## Code Style

Run `make lint` to check formatting. Exported functions require doc
comments. Keep functions under 50 lines where practical.
