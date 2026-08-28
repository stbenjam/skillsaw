---
description: Run a Lighthouse audit against the local web build
---

OpenCode merges every `.opencode/` between the working directory and the
worktree root, so this one is read when `apps/web` is the workspace.

<!-- skillsaw-assert content-weak-language -->
You should probably warm the cache before measuring.

Run `pnpm lighthouse` and report the performance score.
