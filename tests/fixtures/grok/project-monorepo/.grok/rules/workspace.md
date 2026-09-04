# Working across the workspace

- A change touching more than one crate needs `cargo test --workspace`,
  not the per-crate suite.
- Version bumps go through `cargo release --workspace`. Editing a
  `Cargo.toml` version by hand leaves the lockfile behind.
- Never add a path dependency that points outside `packages/`.
