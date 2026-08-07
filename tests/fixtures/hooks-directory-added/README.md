# monorepo-dir-hooks

Prepares a monorepo service directory that is attached to a running
session with `/add-dir` or the SDK `register_repo_root` control request.

## Hooks

| Event            | What it does                                            |
| ---------------- | ------------------------------------------------------- |
| `DirectoryAdded` | Installs the newly added directory's dependencies       |
| `CwdChanged`     | Re-exports the environment with `direnv` after a `cd`   |

The `DirectoryAdded` matcher is `slash_command`, so the hook fires for
`/add-dir` and not for directories passed with the `--add-dir` startup
flag — `SessionStart` covers those.
