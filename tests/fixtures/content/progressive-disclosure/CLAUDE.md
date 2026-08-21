# sprocketd

sprocketd is a Go daemon that syncs sprocket inventory between the
warehouse database and the storefront cache.

## Building

Build with the vendored toolchain, not the system Go: the storefront
protobufs are generated with a pinned protoc and drift if regenerated
with anything newer. Run the build through the wrapper script so the
pinned versions are picked up, and rebuild the protobufs only when the
schema directory changes. If the build complains about a missing
codegen header, clear the build cache first and retry before doing
anything else; a stale cache is the cause nine times out of ten.

## Testing

Integration tests need the compose stack up before they run, and the
stack takes about thirty seconds to become healthy. Do not start the
test suite until the health endpoint reports ready, or the first three
suites will fail with connection-refused errors that look like real
failures. Unit tests are safe to run at any time. The inventory
reconciliation tests are order-dependent within their file; run the
whole file, never a single test from it.

## Deploying

Deploys go through the staging channel first, always. The staging
environment shares a message bus with production, so never point a
load generator at staging. After the staging soak, promotion requires
a signed manifest; the signing key rotates monthly and the old key
keeps working for 48 hours after rotation. If a deploy is rejected
with a signature error inside that window, re-sign with the new key
rather than retrying.

## Database migrations

Migrations must be reversible, and the down migration is exercised in
CI. Column drops are two-release operations: stop reading in one
release, drop in the next. The reconciliation job holds a long
transaction during its nightly run between 02:00 and 02:30 UTC, so
schedule migration deploys outside that window or the migration will
deadlock against it and roll back after a ten-minute wait.
