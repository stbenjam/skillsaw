# OpenAI Codex plugins and marketplaces

<!-- Repo-root-relative src/... and cross-reference paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Codex plugins mirror Claude Code plugins conceptually but use a different manifest
directory and a different schema, so they get their own rules. OpenAI publishes **no
JSON Schema** — parts of the surface are documented only in prose, and others only in
a validator script bundled inside a skill — so skillsaw's rules hedge where the docs
hedge (see Sync notes).

## Upstream source(s)
- Spec: https://developers.openai.com/plugins/build/plugins — the `.md` twin at
  https://developers.openai.com/plugins/build/plugins.md is the authoritative text;
  the rendered HTML page summarizes poorly and has produced invented constraints
  (an `ON_FIRST_USE` value that appears nowhere in either source).
- Field-level spec: `codex-rs/skills/src/assets/samples/plugin-creator/references/plugin-json-spec.md`
  in https://github.com/openai/codex. Shipped inside the `plugin-creator` skill rather
  than on the docs site, so it is easy to miss — and it is stricter than the prose spec:
  it enumerates `policy.authentication` as `ON_INSTALL` / `ON_USE`, documents `logoDark`,
  and requires strict semver for `version`. Check it on every sync; the two can drift
  apart from each other.
- Skill metadata spec: https://learn.chatgpt.com/docs/build-skills#optional-metadata —
  the prose documentation for `agents/openai.yaml`. Field-level sources live in
  https://github.com/openai/codex, again inside bundled skills rather than on the docs
  site: `codex-rs/skills/src/assets/samples/skill-creator/references/openai_yaml.md`
  gives the field-by-field descriptions, and
  `codex-rs/skills/src/assets/samples/plugin-creator/scripts/validate_plugin.py` is the
  executable validator — the actual origin of constraints the prose never states, such
  as the `#RRGGBB` brand-color format (`HEX_COLOR_RE` at `validate_plugin.py:25`,
  applied at `:522-527`). Check all three; each documents things the others omit.
- Reference corpus: https://github.com/openai/plugins — the official catalog (roughly
  180 plugins across `marketplace.json` and `api_marketplace.json`; the count moves).
  It is the de-facto conformance suite: skillsaw must stay silent on it.
- Third-party schema (unofficial, one author's reading — useful for cross-checking,
  not authoritative): https://github.com/typeforged/codex-plugin-marketplace

## What to check
- **Manifest paths**: `.codex-plugin/plugin.json` and `$REPO_ROOT/.agents/plugins/marketplace.json`.
  Codex also reads `~/.agents/plugins/marketplace.json` (out of scope — not in a repo)
  and `$REPO_ROOT/.claude-plugin/marketplace.json` (owned by the Claude rules).
- **plugin.json fields**: new top-level or `interface` fields; re-check the
  constraints and deliberate non-checks recorded in the Sync notes below.
- **Path rules**: the "start with `./`, resolve relative to the plugin root, stay
  inside the plugin root" wording, and which fields it covers.
- **`.codex-plugin/` exclusivity**: the "Only `plugin.json` belongs in `.codex-plugin/`"
  statement.
- **marketplace.json**: source types and their required fields; the `policy` and
  `category` requirements; `npm` `registry` constraints.
- **Enum drift**: `policy.installation` and `policy.authentication` values.
- **`agents/openai.yaml`**: the `interface`, `policy`, and `dependencies` schema for
  skill metadata (and the observed plugin-root form). Re-check `_INTERFACE_STRINGS`,
  the `dependencies.tools` entry keys, and `_BRAND_COLOR` against `openai_yaml.md`
  and `validate_plugin.py` — see the Sync notes.

## skillsaw rules that map
- `src/skillsaw/rules/builtin/codex/`: `codex-plugin-json-valid`,
  `codex-plugin-structure`, `codex-marketplace-json-valid`,
  `codex-marketplace-registration`, `codex-openai-metadata`.
- Repository types — `src/skillsaw/repo_type.py` defines the
  `RepositoryType` enum (`CODEX_PLUGIN`, `CODEX_MARKETPLACE`); add a
  member there. `src/skillsaw/context.py` re-exports the name, so an
  edit made there works and is still in the wrong file.
- Detection — `src/skillsaw/context.py` (`_discover_codex_plugins`,
  `_discover_codex_marketplaces`); the state-free discovery walks live
  in `src/skillsaw/discovery/codex.py`.
- Lint tree nodes — `src/skillsaw/lint_target.py` (`CodexPluginNode`, the
  container every prose attachment and provenance gate hangs off;
  `CodexPluginConfigNode`; `CodexMarketplaceConfigNode`), built in
  `src/skillsaw/lint_tree.py`.
- Docs: `src/skillsaw/rules/docs/codex-*.md`.

## Sync notes
Hand-copied value sets that drift — re-check each against upstream:

- `_SOURCE_REQUIRED_FIELDS` in `codex/marketplace_json_valid.py`: `local`→`path`,
  `url`→`url`, `git-subdir`→`url`+`path`, `npm`→`package`. Unknown types warn rather
  than error, so a type added upstream produces one warning instead of failing the
  lint until skillsaw catches up.
- `DEFAULT_INSTALLATION_VALUES` = `AVAILABLE`, `INSTALLED_BY_DEFAULT`, `NOT_AVAILABLE`.
  The two upstream sources disagree on strictness: the prose spec (`plugins.md`)
  hedges — "Use `policy.installation` values **such as** `AVAILABLE`, …" — an open
  list, while the field-level spec (`openai/codex` `plugin-json-spec.md`) closes it
  ("Allowed values: `NOT_AVAILABLE`, `AVAILABLE`, `INSTALLED_BY_DEFAULT`"). skillsaw
  warns on unrecognized values as the intersection of the two, and the list is
  configurable, so an upstream addition degrades to one warning per entry rather
  than failing the lint until skillsaw catches up. On the next sync, check both
  documents.
- `DEFAULT_AUTHENTICATION_VALUES` = `ON_INSTALL`, `ON_USE`. `plugin-json-spec.md`
  publishes exactly this pair as an enum; the prose spec only describes the field and
  uses `ON_INSTALL` in its examples. Two upstream documents of differing strictness,
  so check both.
- `_PATH_FIELDS` / `_INTERFACE_PATH_FIELDS` in `codex/plugin_json_valid.py`.
  `plugin-json-spec.md` documents `logoDark` and requires every asset path to point at
  a real file inside the plugin. Watch for fields being added to that list.
- `_INTERFACE_STRINGS` in `codex/openai_metadata.py` = `display_name`,
  `short_description`, `icon_small`, `icon_large`, `brand_color`, `default_prompt`.
  Must match `openai_yaml.md`'s field list and `validate_plugin.py`'s interface
  allow-list — both change without a schema publication.
- `dependencies.tools` entry keys in `codex/openai_metadata.py` = `type`, `value`,
  `description`, `transport`, `url` (each checked as a string). Hand-copied from
  `openai_yaml.md`.
- `_BRAND_COLOR` in `codex/openai_metadata.py`: `#RRGGBB`, six hex digits, no
  shorthand, no CSS keywords. Transcribed from `validate_plugin.py:25`
  (`HEX_COLOR_RE`), applied at `:522-527` — the validator publishes no schema, so
  this regex is the only statement of the rule and can drift silently.

Deliberate non-checks — do not "fix" these without a spec change. Each records what
upstream requires and why skillsaw does not enforce it.

- `version` is not validated against semver, though `plugin-json-spec.md` requires
  strict semver and the whole reference corpus conforms. Not enforced because the
  prose spec is silent and a version scheme is the kind of thing a plugin author
  should not have a linter argue with. Enforcing it would be defensible.
- `category` values are not validated. No enum is published anywhere, and openai/plugins
  alone uses eleven distinct values.
- `mcpServers` accepts a path string or an inline object per `plugin-json-spec.md`;
  skillsaw accepts both and routes the object through `CodexInlineMcpBlock`.
- For compatibility with the loader and the official corpus, an array-valued `skills`
  is flattened and every element is checked as a path.
- Unknown keys in `agents/openai.yaml` are accepted, though `validate_plugin.py`
  rejects them at every level. A field added upstream must not break users' lints
  before skillsaw learns it; the validator is the strict gate, skillsaw is not.
- `short_description` length is not enforced, though `openai_yaml.md` requires
  25–64 characters. UI copy length is presentation guidance, not a load-bearing
  constraint.
- `dependencies.tools[].type` is checked as a string only, though upstream documents
  `mcp` as the sole value. A one-value enum is the most likely to grow; string-typing
  it keeps skillsaw silent when it does.
- `default_prompt` is not required to mention `$skill-name`, though `openai_yaml.md`
  asks for it. A phrasing convention for the picker UI, not a correctness rule.
- The plugin-root `agents/openai.yaml` form appears in the official catalog but in no
  spec — `validate_plugin.py:454` reads only the skill-root path. skillsaw supports it
  as observed catalog compatibility; do not tighten it to skill-root semantics without
  upstream documenting it.

## Regression check
Clone https://github.com/openai/plugins and run skillsaw's `codex-*` rules against it.
It must report zero violations; anything it reports is a false positive in our rules,
not a bug in the catalog.
