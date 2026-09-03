# Platform monorepo

Each service under `services/` builds and deploys independently. Run
`make test` from the service directory you changed, not from the root.

Codex is normally started from a service directory, so each service keeps
its own `.codex/` layer.
