# Internal tooling

A small monorepo of CLI helpers. Build with `make build`; the binaries land
in `dist/` and are published from CI, never from a developer machine.

The session hooks below pull the shared toolchain installer, which is how
new checkouts get the pinned `protoc` without a manual step. The second
hook runs a checked-in script on Unix and falls back to the installer on
Windows through `commandWindows`.
