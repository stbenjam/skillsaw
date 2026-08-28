## Why

`metadata.openclaw` drives real runtime behavior: platform gating (`os`),
activation requirements (`requires`), and dependency installation
(`install`). OpenClaw validates it loosely and **silently ignores fields
it doesn't recognize** — an invalid `kind`, `os`, or `archive` value
produces no error, the skill just quietly misbehaves (e.g. an installer
that never appears in `openclaw skills info`). This rule catches those
mistakes at author time.

See the [OpenClaw skills spec](https://docs.openclaw.ai/tools/skills) for
the authoritative field list.

## Allowed values

| Field | Values |
|---|---|
| `install[].kind` | `brew`, `node`, `go`, `uv`, `download` |
| `os`, `install[].os` | `darwin`, `linux`, `win32` |
| `install[].archive` | `tar.gz`, `tar.bz2`, `zip` |
| `requires` keys | `bins`, `anyBins`, `env`, `config` |
| `install[].sha256` | 64 hex digits, `download` entries only |

## How to fix

Correct the flagged field to an allowed value. Each kind needs its
field, or OpenClaw silently drops the installer: `brew`→`formula` (or
`cask`), `node`/`uv`→`package`, `go`→`module`, `download`→`url`. Note
`npm` isn't a kind (use `node`), `type` is an accepted alias for `kind`,
and there's no `apt`/`dnf` kind (use `brew`, which also runs on Linux,
or `download`).

A `download` entry's optional `sha256` pins the artifact. OpenClaw
requires exactly 64 hex digits and drops the entire install entry when
the digest is malformed, so a typo removes the installer rather than
skipping the checksum. `kind` and `archive` are matched
case-insensitively, so `DOWNLOAD` and `ZIP` are accepted.

This rule only fires when `metadata.openclaw` is present — removing the
block suppresses it entirely.
