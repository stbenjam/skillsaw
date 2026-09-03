# Internal tooling

A small monorepo of CLI helpers. Build with `make build`; the binaries land
in `dist/` and are published from CI, never from a developer machine.

The session hook below pulls the shared toolchain installer, which is how
new checkouts get the pinned `protoc` without a manual step.
