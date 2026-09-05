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
- Hooks: https://developers.openai.com/codex/hooks — hook sources, lifecycle events,
  handler types, and per-handler fields. Configuration definitions live in
  `codex-rs/core/config.schema.json`; aliases, JSON nullability and JSON/TOML wrapper
  differences require `codex-rs/config/src/hook_config.rs`. The generated TOML
  schema omits nullable types, so it is insufficient for JSON validation.
  `codex-rs/hooks/schema/generated` describes event input/output payloads, not hook
  configuration. Read each source at the supported release tag: `main` may carry
  fields no released host accepts.

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
- **Hooks**: where Codex loads them from — `~/.codex/hooks.json`, inline `[hooks]`
  tables in `~/.codex/config.toml`, `<repo>/.codex/hooks.json`, `<repo>/.codex/config.toml`,
  and a plugin's `hooks/hooks.json` (or a manifest `hooks` entry: a `./`-prefixed path,
  an array of such paths, an inline hooks object, or an array of inline objects). The 12
  events: `SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop`, `PreToolUse`,
  `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `UserPromptSubmit`,
  `Stop`, `Interrupt`. `command` and `mcp_tool` handlers run; `prompt` and `agent` are
  parsed and skipped.
- **Hook handler fields**: `command` handlers require `command` and take
  `commandWindows`, `timeout` (seconds, default `600`), `statusMessage`,
  `additionalContextLimit` and `async`; `mcp_tool` handlers require `server` and `tool`
  and take `input`, `timeout` and `statusMessage`. `async` is command-only.
  `SessionEnd` and `Interrupt` default to a
  1-second timeout and cap configured timeouts at 3 seconds; `SessionEnd` rejects
  `mcp_tool` handlers. `matcher` is honored on `PermissionRequest`, `PostToolUse`,
  `PreToolUse`, `PreCompact`/`PostCompact` (compaction trigger), `SessionStart`,
  `SubagentStart`/`SubagentStop`, and `SessionEnd`; `UserPromptSubmit`, `Stop`, and
  `Interrupt` ignore any configured `matcher`.
- **Hook failure scopes** — measured against codex-cli 0.153.0 (canary hooks in a
  trusted project, offline). Three scopes, and they are what `codex-hooks-valid`'s
  severities and messages encode:
  - *File-scoped fatal in `<repo>/.codex/config.toml`* — `codex` exits 1 and starts
    no session: TOML syntax error; an event value that is not a sequence; a handler
    missing `type` or `command`; a `timeout` that is not an integer (it is a `u64`,
    so `1.5` and `"30"` both fail); an unknown handler `type` variant. **The same
    defects in `hooks.json` are entry-scoped**: one `warning: failed to parse hooks
    config <path>` and the session runs. Any new check belongs on the same split.
  - *Entry-scoped warning in both files* — `prompt` and `agent` handlers, `mcp_tool`
    on `SessionEnd`, a `SessionEnd` timeout over the 3s clamp. Codex names the file
    and carries on.
  - *Silent, no diagnostic under any flag* — an unknown event name, an unknown
    handler key, an unknown event-group key, a `matcher` on an event that ignores
    one. `--strict-config` is fatal for an unknown key at the top level of
    `config.toml` and never descends into `[hooks]` (verified with a control), so
    skillsaw is the only thing that will ever report these.
  `timeout` is an `Option<u64>` and `additionalContextLimit` an `Option<usize>`,
  in both files. Measured against 0.153.2: `timeout = -1` and
  `additionalContextLimit = -1` are each fatal in `config.toml` (`invalid value:
  integer \`-1\`, expected u64` / `expected usize`) and each drop a `hooks.json`
  with the same message under a `failed to parse hooks config` warning;
  `timeout = 0` loads. No upper bound is needed — a TOML integer stops at `i64`.
  skillsaw enforces the range on the TOML file only: the looser number is what
  `hooks-json-valid` released for `hooks.json`, and tightening it would newly
  fail files that pass today.
  `command_windows` is a serde *alias* for `commandWindows`, so a handler
  carrying both is a duplicate field. Measured against 0.153.2: a `config.toml`
  exits 1 with `Error loading config.toml: duplicate field \`commandWindows\``
  and a `hooks.json` is dropped with the same message. Only on a handler type
  that owns the field — an `mcp_tool` handler carrying both spellings loads,
  because neither is a field of that variant.
  Also confirmed against the binary in the same pass: the 12 event names as the
  complete enum, the four handler types, the required fields per type, the
  `mcp_tool`-on-`SessionEnd` rejection, and the 3s `SessionEnd` clamp. Not
  measured, carried from the docs: the 1s default timeout, and the `matcher`
  semantics of the events that need a model turn.
- **Project trust gate**: a project-layer hooks file — either one — runs only when
  the user config carries `projects."<abs path>".trust_level = "trusted"`.
  `--dangerously-bypass-hook-trust` is a *different* gate and does not substitute.
  Not repository-resident, so it never suppresses a finding; the rule doc says so.
- **Layer discovery**: Codex merges a `.codex/` layer from every directory from the
  git repo root down to the cwd, inclusive, and reads nothing above the root. A
  committed nested `.codex/config.toml` is therefore live for anyone working in
  that subtree, which is why the lint tree attaches every one it finds.

- **`[mcp_servers.<name>]`** — the project's MCP servers; there is no
  `.codex/mcp.json`. Measured against 0.153.0 with `codex mcp list --json`, which
  runs offline and prints the transport Codex derived, and re-confirmed at 0.153.2
  with `codex exec --strict-config`:
  - `command` selects stdio and `url` streamable HTTP, and they are **mutually
    exclusive**. A table carrying both is refused with `url is not supported for
    stdio in \`mcp_servers.<name>\``, one carrying neither with `invalid transport`
    — each fatal for the whole file, so `codex` exits 1 and `codex mcp list` prints
    nothing. The key alone picks the transport, whatever its value: `command = ""`
    loads as stdio, `url = ""` as streamable HTTP, and `command = ["npx"]` refuses
    the whole file (`invalid type: sequence, expected a string`) rather than
    reading the table some other way.
  - **No server field vocabulary is kept**, deliberately. An unknown server key
    loads silently, so watching a table load proves nothing about whether its
    keys are real; only `--strict-config` names one (`unknown configuration field
    \`mcp_servers.<name>.enviroment\``), and it does so for every malformed
    server table, which is why skillsaw adds no shape rule here. The tables reach
    `mcp-prohibited` and `mcp-valid-json`'s dialect-neutral checks through the MCP
    role on `CodexConfigBlock`, and nothing restates the refusals.
  - `env` is the one server field that holds literal values, so it is the one in
    `credential_maps` beside `http_headers`. `env_vars` is a *sequence* under
    `--strict-config` (`invalid type: map, expected a sequence`) whose entries
    name an env-var source, and `env_http_headers`/`bearer_token_env_var` hold
    env-var names, so none of the three can carry a committed secret.
  - Same gates as the hooks: a project layer's servers are read only once the user
    config trusts the directory, and layers merge from the repo root down to the
    cwd. A name declared in both the user config and a project layer resolves to
    the project's.

## skillsaw rules that map
- `src/skillsaw/rules/builtin/codex/`: `codex-plugin-json-valid`,
  `codex-plugin-structure`, `codex-marketplace-json-valid`,
  `codex-marketplace-registration`, `codex-openai-metadata`.
- Detection — `src/skillsaw/context.py` (`RepositoryType.CODEX_PLUGIN`,
  `RepositoryType.CODEX_MARKETPLACE`, `_discover_codex_plugins`,
  `_discover_codex_marketplaces`); the state-free discovery walks live
  in `src/skillsaw/discovery/codex.py`.
- Lint tree nodes — `src/skillsaw/lint_target.py` (`CodexPluginNode`, the
  container every prose attachment and provenance gate hangs off;
  `CodexPluginConfigNode`; `CodexMarketplaceConfigNode`), built in
  `src/skillsaw/lint_tree.py`.
- Docs: `src/skillsaw/rules/docs/codex-*.md`.
- Hooks — `src/skillsaw/rules/builtin/codex/hooks_valid.py`: `codex-hooks-valid`.
  Vocabulary (events, handler types, per-handler fields) lives in
  `src/skillsaw/formats/codex.py`, not the rule. Both project-layer files reach it
  as a `CodexHooksBlock`; the TOML one is `CodexConfigHooksBlock`, which carries the
  measured behavioural differences as ClassVars (`whole_number_fields`) so the
  rule stays free of per-file branches. The severities are the same on both files:
  the failure-scope asymmetry above is recorded here and in the rule doc, not
  encoded in a message. Two things differ between the two files' messages: the
  noun each syntax uses for a table or an array, which the blocks declare
  (`mapping_noun`, `sequence_noun`), and one check `config.toml` gets and
  `hooks.json` does not — `timeout` and `additionalContextLimit` must be
  non-negative whole numbers there.
- Both-files merge — measured against 0.153.0 and re-confirmed at 0.153.2: a
  `.codex/` layer declaring hooks in both `hooks.json` and `config.toml` loads
  both, runs every handler once, and prints `warning: loading hooks from both
  <hooks.json> and <config.toml>; prefer a single representation for this layer`. Nothing is dropped and nothing
  wins, which is why `codex-hooks-valid` reports it at INFO with an
  `allow-both-files` escape hatch rather than as a defect.
- MCP — `src/skillsaw/blocks/codex.py`: `CodexConfigBlock` and `GrokConfigBlock`
  share a `TomlMcpConfigBlock` base (`src/skillsaw/blocks/toml_config.py`) and
  differ only in `servers_key`, `credential_maps`, `shape_deferral` and a
  `transport()` hook — `codex_mcp_transport()` in `formats/codex.py`. The
  deferral is unconditional, so the JSON shape walk stands down and
  `codex-hooks-valid` owns the one parse-error finding for the file. No Codex MCP
  shape rule exists by design — see the measured note above.

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
- The `CODEX_HOOK_*` constants in `formats/codex.py` (events, handler types,
  required/optional per-handler fields, which events honor `matcher`, which reject
  `mcp_tool`, and the `SessionEnd`/`Interrupt` short-timeout events), read by
  `codex/hooks_valid.py`: re-check against https://developers.openai.com/codex/hooks
  and the configuration schema/source listed above, read at the supported
  release's tag rather than on `main`, on every sync. Use the event input/output
  schemas only for payload contracts.
- The TOML dialect of the project layer's `[hooks]` tables, mapped by
  `codex_config_hooks()` in `formats/codex.py` — the one place the mapping lives.
  `[[hooks.<Event>]]` renders to a `{matcher?, hooks: [...]}` entry and
  `[[hooks.<Event>.hooks]]` to a handler, which is the JSON shape exactly, so the
  mapping is a pass-through apart from the `state` key below. Re-check on every
  sync: a dialect that stops matching turns the mapping into a rename.
- **Handler field aliases** — `CODEX_HOOK_FIELD_ALIASES` in `formats/codex.py`.
  `command_windows` is a real alias of `commandWindows`:
  `codex-rs/config/src/hook_config.rs` declares
  `#[serde(default, rename = "commandWindows", alias = "command_windows")]`, and the
  hooks documentation tells TOML authors to write the snake_case one. Both load, in
  both files.
  **A field list read from the shipped binary cannot see an alias.** Serde's
  `unknown field ..., expected one of ...` message enumerates `rename` names only,
  so `strings` over the binary — and any experiment that reads that error — is
  systematically blind to exactly this. Re-derive every field claim from
  `hook_config.rs` at the supported release's tag, never from a serde error.
  `HOOK_COMMAND_FIELDS` keeps both spellings independently: it is the cross-host
  scan union and Muse Code accepts the snake_case one, so a Windows command stays
  in front of `hooks-dangerous` however it is written.
- **`[hooks]` is `HooksToml`, not `HooksFile.hooks`.** The TOML table is a superset
  of the JSON file's object: upstream flattens the event map into it
  (`#[serde(flatten)] events: HookEventsToml`) and adds a sibling
  `state: BTreeMap<String, HookStateToml>` — per-hook `enabled` and `trusted_hash`,
  which only the user layer gets to write. Measured, 0.153.0: a project layer
  carrying `[hooks.state."<key>"]` starts normally and its sibling hooks fire, with
  no diagnostic. `codex_config_hooks()` drops the key
  (`CODEX_CONFIG_HOOKS_STATE_KEY`) before the document reaches the rule; without
  that it reads as an event whose value is not a sequence, which is an ERROR
  claiming the CLI will not start. Re-check on every sync for a second non-event
  sibling.

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
