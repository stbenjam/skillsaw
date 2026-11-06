# OpenClaw

<!-- Repo-root-relative src/... and cross-reference paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

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
  `formula`, `package`, `module`, `url`, `sha256`, `archive`, `extract`,
  `stripComponents`, `targetDir`) and the `kind` union
  `"brew" | "node" | "go" | "uv" | "download"`; and
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
- The `sha256` pattern in `parseInstallSpec` (`frontmatter.ts`) vs `SHA256_DIGEST`, and
  which kinds it is read for (`download` only today).
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
  - `VALID_OS_VALUES = {"darwin", "linux", "win32"}`, plus `OS_ALIASES = {"macos": "darwin"}`
  - `VALID_ARCHIVE_TYPES = {"tar.gz", "tar.bz2", "zip"}`
  - `SHA256_DIGEST` = 64 hex digits, transcribed from `parseInstallSpec`
- `kind` and `archive` are trimmed and lowercased upstream before matching
  (`normalizeOptionalLowercaseString`); the rule normalizes both the same way, so
  do not tighten either comparison to be case-sensitive.
- `os` values, top-level and `install[].os`, are trimmed, lowercased, and
  `macos` maps to `darwin` (`normalizeOsRequirementPlatform` in
  `src/shared/requirements.ts`, used by `isOsRequirementSatisfied` in
  `src/skills/discovery/status.ts`). The rule applies the same normalization.
- Last synced against release `v2026.11.1`. That release retired the
  `metadata.clawdbot` alias; skillsaw never read it, so no change was needed.
- OpenClaw validates loosely and silently ignores unrecognized fields, so upstream
  additions won't surface as errors — you must read the types to catch them.
- No upstream JSON Schema exists; skillsaw's rule is the only validator, so keep it
  aligned with the code, not the docs.
- Complementary verification: the runtime validator `openclaw skills check --json` can
  cross-check a real skill against the installed OpenClaw version.

## Native plugins

Inspected September 18, 2026 at OpenClaw revision
[`912b21b98581c0be3baad87fe3686b64d69fffeb`](https://github.com/openclaw/openclaw/tree/912b21b98581c0be3baad87fe3686b64d69fffeb).

- `openclaw-manifest-valid`: `src/skillsaw/rules/builtin/openclaw/manifest_valid.py`;
  documentation: `src/skillsaw/rules/docs/openclaw-manifest-valid.md`.
- `openclaw-package-valid`: `src/skillsaw/rules/builtin/openclaw/package_valid.py`;
  documentation: `src/skillsaw/rules/docs/openclaw-package-valid.md`.
- `openclaw-resources`: `src/skillsaw/rules/builtin/openclaw/resources.py`;
  documentation: `src/skillsaw/rules/docs/openclaw-resources.md`.
- Discovery and normalization: `src/skillsaw/discovery/openclaw.py` and
  `src/skillsaw/formats/openclaw.py`.
- Regression coverage: `tests/test_integration_openclaw.py` and
  `tests/fixtures/openclaw/`.

On each maintenance pass, verify these native loader contracts:

- `src/plugins/manifest.ts`: JSON5, the 256 KiB byte limit, non-empty `id`,
  reserved case-insensitive `node-mcp` identity, and object `configSchema`.
- `src/plugins/package-manifest.ts` and discovery: `openclaw.extensions`
  detection, null/missing index fallback and empty-array suppression. Hook-only
  packs are not native plugin claims.
- `src/skills/loading/plugin-skills.ts`: explicitly declared skill roots,
  containment and absence of a conventional `skills/` fallback.
- `src/plugins/manifest-capability-normalizers.ts` and
  `src/infra/prototype-keys.ts`: MCP names are trimmed; empty names, prototype
  keys and non-object records are discarded by the host before runtime loading.

All 155 bundled native plugins passed the required manifest and package-shape
checks. This is one upstream repository, not 155 independent adoption samples;
the new rules therefore remain opt-in. One declared dependency-provided skill
root was absent before dependency installation. External plugin code was not run.

Native package metadata uses the host’s 16 MiB read limit from
`src/plugins/plugin-cache-files.ts`. Recheck it alongside the manifest’s
256 KiB limit when updating the pinned loader contract.

### Theme declarations

Verified against released
[`v2026.11.1`](https://github.com/openclaw/openclaw/releases/tag/v2026.11.1).
The existing opt-in `openclaw-manifest-valid` rule validates declarations in
`src/skillsaw/formats/openclaw_themes.py`; regression coverage lives in
`tests/test_openclaw_themes.py` and `tests/fixtures/openclaw/themes/`.

- [`manifest-themes.ts`](https://github.com/openclaw/openclaw/blob/v2026.11.1/src/plugins/manifest-themes.ts)
  rejects malformed theme arrays and artwork declarations before plugin loading.
  Check the 32-theme limit, theme field allowlist, duplicate IDs, relative JSON/SVG
  paths, and the eight-entry limits for each artwork kind (`icons`, `hats`,
  `critters`). Duplicate artwork object keys are
  rejected from the original JSON5 source, even if normal parsing overwrites them.
- [`theme.ts`](https://github.com/openclaw/openclaw/blob/v2026.11.1/packages/gateway-protocol/src/theme.ts)
  owns the name/description limits (80/320 UTF-16 units), artwork ID pattern,
  built-in brand icons (`claw`, `mark`), built-in hats (`fedora`, `crown`,
  `santa`, `party`, `pumpkin`), and built-in critters (`penguin`, `fedora`).
  Declared artwork IDs must lie outside the matching catalog. Recheck these copied sets each pass.
- [`theme-ids.ts`](https://github.com/openclaw/openclaw/blob/v2026.11.1/packages/gateway-protocol/src/theme-ids.ts)
  defines portable plugin ownership, the reserved personal-theme namespace, and
  the 64-character lowercase local ID pattern. Preserve scoped and multi-entry
  plugin IDs.
- Deliberately omitted: theme JSON content, SVG content, and asset existence.
  Invalid assets omit a theme with a warning rather than rejecting the plugin;
  they do not belong to this ERROR-level manifest check. See the
  [theme packaging reference](https://github.com/openclaw/openclaw/blob/v2026.11.1/docs/plugins/manifest/surfaces.md#themes).
