# OpenAI Codex plugins and marketplaces

<!-- Repo-root-relative src/... and cross-reference paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Codex plugins mirror Claude Code plugins conceptually but use a different manifest
directory and a different schema, so they get their own rules. OpenAI publishes **no
JSON Schema**, and several documented value sets are explicitly open-ended, so
skillsaw's rules hedge where the docs hedge (see Sync notes).

## Upstream source(s)
- Spec: https://developers.openai.com/plugins/build/plugins — the `.md` twin at
  https://developers.openai.com/plugins/build/plugins.md is the authoritative text;
  the rendered HTML page summarizes poorly and has produced invented constraints
  (a "semver" requirement and an `ON_FIRST_USE` value that appear nowhere in the source).
- Reference corpus: https://github.com/openai/plugins — the official catalog (180
  plugins across `marketplace.json` and `api_marketplace.json`). It is the de-facto
  conformance suite: skillsaw must stay silent on it.
- Third-party schema (unofficial, one author's reading — useful for cross-checking,
  not authoritative): https://github.com/typeforged/codex-plugin-marketplace

## What to check
- **Manifest paths**: `.codex-plugin/plugin.json` and `$REPO_ROOT/.agents/plugins/marketplace.json`.
  Codex also reads `~/.agents/plugins/marketplace.json` (out of scope — not in a repo)
  and `$REPO_ROOT/.claude-plugin/marketplace.json` (owned by the Claude rules).
- **plugin.json fields**: new top-level or `interface` fields; any newly stated
  requiredness or format constraint (today only `name` kebab-case is stated).
- **Path rules**: the "start with `./`, resolve relative to the plugin root, stay
  inside the plugin root" wording, and which fields it covers.
- **`.codex-plugin/` exclusivity**: the "Only `plugin.json` belongs in `.codex-plugin/`"
  statement.
- **marketplace.json**: source types and their required fields; the `policy` and
  `category` requirements; `npm` `registry` constraints.
- **Enum drift**: `policy.installation` and `policy.authentication` values.

## skillsaw rules that map
- `src/skillsaw/rules/builtin/codex/`: `codex-plugin-json-valid`,
  `codex-plugin-structure`, `codex-marketplace-json-valid`,
  `codex-marketplace-registration`.
- Detection and discovery — `src/skillsaw/context.py`
  (`RepositoryType.CODEX_PLUGIN`, `RepositoryType.CODEX_MARKETPLACE`,
  `_discover_codex_plugins`, `_discover_codex_marketplaces`).
- Lint tree nodes — `src/skillsaw/lint_target.py` (`CodexPluginConfigNode`,
  `CodexMarketplaceConfigNode`), built in `src/skillsaw/lint_tree.py`.
- Docs: `src/skillsaw/rules/docs/codex-*.md`.

## Sync notes
Hand-copied value sets that drift — re-check each against upstream:

- `_SOURCE_REQUIRED_FIELDS` in `codex/marketplace_json_valid.py`: `local`→`path`,
  `url`→`url`, `git-subdir`→`url`+`path`, `npm`→`package`. Unknown types warn rather
  than error, so a type added upstream produces one warning instead of failing the
  lint until skillsaw catches up.
- `DEFAULT_INSTALLATION_VALUES` = `AVAILABLE`, `INSTALLED_BY_DEFAULT`, `NOT_AVAILABLE`.
  The docs say "values such as", so this is open-ended by design — unrecognized values
  warn, and the list is configurable.
- `DEFAULT_AUTHENTICATION_VALUES` = `ON_INSTALL`, `ON_USE`. The docs describe the field
  in prose and use `ON_INSTALL` in their examples, but publish no enum. `ON_USE` appears
  nowhere upstream — it comes from the openai/plugins catalog alone, and is the highest
  drift risk in this reference.
- `_PATH_FIELDS` / `_INTERFACE_PATH_FIELDS` in `codex/plugin_json_valid.py`.
  `logoDark` is in that list but is **undocumented** — it appears on roughly a quarter
  of openai/plugins' manifests. Watch for it being documented or dropped.

Deliberate non-checks — do not "fix" these without a spec change:

- `version` is not validated against semver. The spec never constrains its format.
- `category` values are not validated. No enum is published, and openai/plugins alone
  uses eleven distinct values.
- Undocumented-but-real shapes (an inline `mcpServers` object, an array-valued
  `skills`) warn rather than error, because Codex mirrors Claude Code's plugin loader.

## Regression check
Clone https://github.com/openai/plugins and run skillsaw's `codex-*` rules against it.
It must report zero violations; anything it reports is a false positive in our rules,
not a bug in the catalog.
