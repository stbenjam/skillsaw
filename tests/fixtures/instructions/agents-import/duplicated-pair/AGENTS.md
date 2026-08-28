# Contributor guide for agents

This repository ships a Python service and a small React console. Read the
sections below before changing anything under `src/`.

## Build

Run `make build` to compile the service. Build artifacts land in `dist/`.
Delete that directory before a release build so stale objects never end up
inside the tarball that is uploaded to the package index.

## Testing

Run `make test` before every push. The integration suite talks to a
Postgres container, so start it with `make docker-up` first. Repair a
failing test instead of marking it skipped: a skipped test hides the
regression it was written to catch, and the next person to touch that code
inherits the surprise.

## Style

Format Python with `black` and keep lines under 100 characters. Import
order is enforced by `isort`. Running `make format` applies both, and CI
rejects a branch where the two disagree with the committed tree.
