---
root: false
targets: [claudecode, cursor]
description: HTTP service development
globs: ["src/**/*.ts"]
cursor:
  alwaysApply: false
---
# HTTP API

You should consider adding a regression test when changing reservation logic.
Return a stable error code when a reservation cannot be fulfilled.
