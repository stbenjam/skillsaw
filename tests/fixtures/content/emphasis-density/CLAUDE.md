# Project Standards

sprocketd is a Go daemon that syncs sprocket inventory. Use these
notes for every change in this repository.

## Rules

- IMPORTANT: run `go test ./...` before committing.
- You MUST update the OpenAPI spec when handlers change.
- NEVER log request bodies — they contain customer addresses.
- ALWAYS regenerate mocks with `make mocks` after interface edits.
- CRITICAL: keep migrations reversible and numbered sequentially.
- Database credentials are REQUIRED to come from the vault helper.
- WARNING: the staging cluster shares a message bus with production.
