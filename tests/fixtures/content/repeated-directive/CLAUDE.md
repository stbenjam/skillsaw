# Project Standards

gadgetron-api is a FastAPI service behind the gadget storefront. Use
these notes for every change in this repository.

## Testing

- Run `make test` before every push.
- Mark end-to-end tests with the `e2e` marker so CI shards them onto
  the slow pool. The suite spins up a Redis container automatically.

## Git workflow

Create feature branches from `main` and rebase instead of merging when
the branch falls behind. Ask before force-pushing to a shared branch —
someone else may have review comments in flight.

## Releases

- Update the changelog under the Unreleased heading in the same PR as
  the change.
- Run `make test` before every push.
- Tag releases with an annotated tag and push the tag only after the
  release notes are reviewed.

## Destructive operations

Wait for approval before dropping database tables or deleting
production data. Use the `ops-runbook` skill for the individual
recovery procedures.
