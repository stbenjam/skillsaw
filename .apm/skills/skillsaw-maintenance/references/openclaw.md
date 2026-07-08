# OpenClaw

Most drift-prone tracked spec. OpenClaw publishes **no JSON Schema**, so skillsaw's
`openclaw-metadata` rule is the de-facto validator. The rule hand-copies value sets that
MUST be re-checked against upstream types on every maintenance pass (see Sync notes).

## Upstream source(s)
Human docs (lag behind the code — do not treat as authoritative):
- https://docs.openclaw.ai/tools/skills — skill metadata
- https://docs.openclaw.ai/tools/skills-config — `openclaw.json` `skills.*` config
- https://docs.openclaw.ai/clawhub/publishing — ClawHub publishing

Authoritative source of truth — the `openclaw/openclaw` GitHub repo (the TypeScript types
ARE the spec):
- `src/skills/types.ts` — `SkillInstallSpec` (fields: `id`, `kind`, `label`, `bins`, `os`,
  `formula`, `package`, `module`, `url`, `archive`, `extract`, `stripComponents`,
  `targetDir`) and the `kind` union `"brew" | "node" | "go" | "uv" | "download"`; and
  `OpenClawSkillMetadata` (`always`, `skillKey`, `primaryEnv`, `emoji`, `homepage`, `os`,
  `requires{bins,anyBins,env,config}`, `install`).
- `src/skills/loading/frontmatter.ts` — per-kind **required fields**: brew→`formula`,
  node→`package`, go→`module`, uv→`package`, download→`url`; plus cask handling.
- `src/shared/frontmatter.ts` — `parseOpenClawManifestInstallBase`: `type` is a fallback
  alias for `kind`, and `kind` is lowercased before validation.
- `src/skills/lifecycle/install.ts` — installer `switch` on `kind` (authoritative allowed
  kinds) plus `SAFE_*` package/formula regexes.

## What to check
- The `kind` union in `types.ts` vs skillsaw's `VALID_INSTALL_KINDS` (top drift risk).
- Allowed `os` values vs `VALID_OS_VALUES`.
- Allowed `archive` types vs `VALID_ARCHIVE_TYPES`.
- Per-kind required install fields (`frontmatter.ts`) vs what the rule requires.
- New metadata fields on `OpenClawSkillMetadata` / `SkillInstallSpec`.
- `requires` keys (`bins`, `anyBins`, `env`, `config`).

## skillsaw rules that map
- `openclaw-metadata` — `src/skillsaw/rules/builtin/openclaw/metadata.py`
- Doc: `src/skillsaw/rules/docs/openclaw-metadata.md`
- Tests: `tests/test_openclaw_rules.py`

## Sync notes
- **Top drift risk.** `metadata.py` hand-copies three constant sets that must be
  re-verified against `src/skills/types.ts` (and `install.ts`) every pass:
  - `VALID_INSTALL_KINDS = {"brew", "node", "go", "uv", "download"}`
  - `VALID_OS_VALUES = {"darwin", "linux", "win32"}`
  - `VALID_ARCHIVE_TYPES = {"tar.gz", "tar.bz2", "zip"}`
- OpenClaw validates loosely and silently ignores unrecognized fields, so upstream
  additions won't surface as errors — you must read the types to catch them.
- No upstream JSON Schema exists; skillsaw's rule is the only validator, so keep it
  aligned with the code, not the docs.
- Complementary verification: the runtime validator `openclaw skills check --json` can
  cross-check a real skill against the installed OpenClaw version.
