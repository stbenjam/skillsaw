# Cross-platform build helpers

A small library the team builds on both Linux and Windows laptops. The
session hooks below prepare the toolchain, taking a different path on each
platform.

## Conventions

- Keep platform-specific shims in `scripts/`, one file per platform.
- A hook that needs a different invocation on Windows sets
  `commandWindows`; a hook that needs one only there sets it alone.
