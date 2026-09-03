# Grok Build

<!-- Repo-root-relative src/... paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Grok Build is xAI's terminal coding agent. A checkout configures it through `.grok/`.
Most of that layer is shared convention other tools read too — portable Agent Skills,
Markdown prose, `AGENTS.md` — so what skillsaw validates that is Grok's alone is its
lifecycle hooks, its subagent frontmatter, and the plugin and marketplace files its
installer reads.

## Upstream source(s)
- The user guide shipped with 1.0.13: `10-hooks.md` (events, the Cursor alias table,
  handler fields, reserved environment variables, the matcher-per-event table),
  `12-project-rules.md` (the `.grok/` layer), `07-mcp-servers.md` (MCP sources),
  `08-skills.md`, `04-slash-commands.md`, `16-subagents.md`, `26-config-reference.md`.
- The shipped executable, whose hook loader is
  `crates/codegen/xai-grok-hooks/src/config.rs`. Its diagnostics name the handler
  contract directly: `command handler requires a 'command' field`, `http handler
  requires a 'url' field`, `hooks: skipped unrecognized event names (check for typos).`,
  and `hook env: ignoring user-supplied value for runner-reserved key (the
  runner-injected value always wins)`.

The docs name the events and the file locations, and everything below was verified
against Grok Build 1.0.13 (`5e9a58528b76`, stable) rather than taken from them. Method:
an isolated `GROK_HOME` (the real `~/.grok` untouched) with one hook file per case
under `$GROK_HOME/hooks/` — user scope, always trusted, so no folder-trust gate — each
handler carrying a unique `command` token, read back from `grok inspect --json`. Every
case carries a canary handler in the same group and a canary group under a different
event in the same file, so file, group and handler scopes are told apart rather than
assumed. `grok inspect --json` reported `configWarnings: null` for every failing case:
the runtime tells the author nothing, which is why `grok-hooks-valid` exists. Re-run
that matrix before changing a rule here.

## What to check
- **Hooks files**: `<project>/.grok/hooks/*.json`, read as a **flat glob** and merged.
  A file in a subdirectory and a file under another extension are both ignored. User
  hooks live in `~/.grok/hooks/` and config hooks in `config.toml`; neither is in the
  repository.
- **Shape**: the nested form Claude Code defined —
  `{"hooks": {Event: [{matcher?, hooks: [handler, ...]}, ...]}}`. Top-level keys other
  than `hooks` are ignored, as are unknown matcher-group keys (`description`) and
  unknown handler keys.
- **Failure scope** is the thing to get right, because it is what the diagnostic is
  worth:
  - *Whole file*: a UTF-8 byte-order mark at the start of the file (`grok inspect
    --json` loaded zero hooks from an otherwise-correct file with a leading BOM;
    skillsaw reads with `utf-8-sig` and would see a valid document, so this is
    checked before anything else); malformed JSON; a bare `NaN`/`Infinity`/`-Infinity`;
    no top-level `hooks` object, or one that is not an object; an event whose value is
    not an array; a matcher group that is not an object; a group with no `hooks` key or
    a non-array one; a `matcher` that is not a string, which never reaches the regex
    compiler; a handler that is not an object; a handler with no `type`, or a `null`
    one; any known handler field carrying the wrong JSON type — including a `timeout`
    above `2**64-1`, the field's own `u64` ceiling, which fails the same way as a float
    or a negative even though the value is a plain non-negative integer. A JSON `null`
    is not one of those wrong types: Grok reads it as the key being absent, so `type`
    is the only field whose `null` costs the file.
  - *That group*: a `matcher` string that does not compile.
  - *That event's entries*: a name outside the events and aliases below.
  - *That handler*: a `command` handler with no `command` or a `null` one, an `http`
    handler with no `url` or a `null` one, a `type` outside `command`/`http`.
  - *Tolerated*: a `null` `timeout`, `env` or `matcher`, and a `null` in any field the
    handler's type does not require — each is the key being absent.
- **Events** (15): `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, `PostToolUseFailure`, `PermissionDenied`, `Stop`, `StopFailure`,
  `StopCancelled`, `Notification`, `SubagentStart`, `SubagentStop`, `PreCompact`,
  `PostCompact`.
- **Aliases**, all normalized and all accepted — a missing one is a false "unknown
  event" on a working file: `SubagentEnd`; the `snake_case` spelling of all 16 names —
  the 15 events above plus `subagent_end`, which is itself an alias for
  `SubagentStop`;
  the `camelCase` spelling of every event **except** `userPromptSubmit`, which is not
  accepted; and Cursor's per-operation names (`beforeShellExecution`,
  `beforeMCPExecution`, `beforeReadFile` → `PreToolUse`; `afterShellExecution`,
  `afterMCPExecution`, `afterFileEdit`, `afterAgentResponse`, `afterAgentThought` →
  `PostToolUse`; `beforeSubmitPrompt` → `UserPromptSubmit`).
- **Handler types**: `command` (a shell command) and `http` (the event envelope POSTed
  to a URL).
- **Handler fields**, with the JSON type each must carry: `type`, `command`, `url`
  (strings); `timeout` (non-negative integer — a float, a negative, a bool and a
  numeric string each refuse the file, while a large value is fine because `Stop` and
  `SubagentStop` default to 600 seconds); `env` (an object of strings). A wrong type on
  any of them refuses the file; a `null` is read as the key being absent; a key outside
  the table is tolerated.
- **Matchers**: compiled at load with Rust's `regex` crate — verified by loading
  `\p{L}+` and `[a-z&&[^aeiou]]`, which Python's `re` rejects, and by watching
  `(?<=x)y` and `(a)\1` drop their groups. `""` and `"*"` are catch-alls, not patterns.
  On `Stop` and `UserPromptSubmit` the matcher is kept in the configuration and never
  compiled, so even an uncompilable one there costs nothing.
- **Reserved `env` keys**, stripped at load with the runner's value winning:
  `GROK_HOOK_EVENT`, `GROK_HOOK_NAME`, `GROK_SESSION_ID`, `GROK_WORKSPACE_ROOT`,
  `CLAUDE_PROJECT_DIR`. A plugin's hooks additionally get `GROK_PLUGIN_ROOT`,
  `GROK_PLUGIN_DATA` and their two `CLAUDE_` aliases.
- **The rest of the layer**: `.grok/skills/**/SKILL.md` (walked recursively),
  `.grok/rules/*.md`, `.grok/commands/*.md` and `.grok/agents/*.md` (each read **flat**
  — a nested file is not loaded). A `.grok/commands/<n>.md` is loaded as a project
  *skill*, which is why `grok inspect` lists it among the skills. The skill-location
  table in `08-skills.md` calls that directory "legacy command markdown", which is
  where `GrokCommandBlock`'s docstring gets the word.
- **Subagent frontmatter**: `.grok/agents/*.md` needs `name` and `description` in
  frontmatter or Grok's loader drops the subagent and reports nothing — it is on
  disk and simply absent from the agent list. An empty value for either key still
  registers; the loader checks presence, not content. Extra keys are tolerated.
  `.grok/commands/*.md` is deliberately not held to the same demand — Grok loads a
  frontmatter-less command file, naming it from the filename, so the same check
  there would be a false positive on a file that works.
- **Trust gate**: hooks, MCP and LSP require folder trust (`/hooks-trust`, `--trust`,
  or `GROK_FOLDER_TRUST=0`); skills, rules, commands and agents load unconditionally.
  Trust is recorded in `~/.grok/trusted_folders.toml`, outside the repository, so it
  changes nothing about what skillsaw lints.
- **There is no `.grok/mcp.json`.** Grok's MCP sources are `config.toml`
  `[mcp_servers]`, `~/.claude.json`, `.cursor/mcp.json` and the repository-root
  `.mcp.json`. A `.grok/mcp.json` placed in a trusted project loaded nothing, and the
  file appears nowhere in the docs. Do not attach it.

## Plugins and the marketplace
A plugin bundles skills, commands, agents, `hooks/hooks.json`, `.mcp.json` and
`.lsp.json` into one installable directory; a marketplace is a repository listing
plugins in `.grok-plugin/marketplace.json`. Both were verified against 1.0.13 by
building catalogs and plugins in an isolated `GROK_HOME` **and** an isolated `HOME` —
`GROK_HOME` alone is not enough, because Grok also reads `~/.claude/settings.json`
`extraKnownMarketplaces` and will start cloning the real marketplaces listed there.
`GROK_FOLDER_TRUST=0` is the *permissive* setting, and `projectRoot` is set only inside
a git repository.

- **Manifest resolution**: `plugin.json` > `.grok-plugin/plugin.json` >
  `.claude-plugin/plugin.json`, first match wins. **Catalog resolution**:
  `.grok-plugin/marketplace.json` > `.claude-plugin/marketplace.json` >
  `./marketplace.json`, exactly one read, never merged — the **reverse** order. The two
  lookups share no ordering, so do not derive one from the other.
- **skillsaw claims only the `.grok-plugin/` spelling of either.** The others are
  another ecosystem's declaration, and adopting them would put every Claude plugin and
  every portable package under Grok's format rules too.
- **A manifest is optional.** A directory holding `skills/`, `agents/`,
  `hooks/hooks.json` or `.mcp.json` installs without one, under a synthesized
  `<dir>-<hash>` name. `commands/` alone and `.lsp.json` alone are discovered but
  refused by `grok plugin install`. So skillsaw claims a manifest-less directory only
  when a catalog lists it as a local source.
- **Manifest failure scope**: unparseable JSON, or a `name` that is missing, non-string
  or outside `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$`, makes discovery **skip the whole
  plugin directory** — `skills/` does not rescue it, `grok plugin install` still prints
  success, and `grok inspect` then shows `plugins: []`. A declared path that escapes the
  plugin root or does not exist costs that component list only, and an override
  *replaces* the conventional directory rather than extending it. A name disagreeing
  with the directory name, a non-semver `version`, an unknown key and a bare string
  where an array is allowed all cost nothing.
- **`hooks` and `mcpServers` are `path | inline`**, not `path | array`. So
  `"hooks": "not-an-object"` is read as a path, found missing, and dropped silently — it
  is not a type error. A malformed inline `hooks` costs the hooks only; the sibling
  `mcpServers`, the skills and the plugin survive.
- **Catalog entry scope**: a missing `name`, a missing `source`, a `path` that does not
  resolve, and a `path` escaping the marketplace root each drop that one entry silently.
  A catalog that fails to parse, or whose `plugins` is not an array, discards the whole
  catalog — and discovery then falls back to scanning `plugins/` only, so a repository
  keeping third-party plugins under `external_plugins/` loses exactly those with no
  diagnostic. **Two entries resolving to one manifest name** are not deduplicated:
  install fails with `Multiple marketplaces provide a plugin named "canary"` and both
  suggested qualifiers are identical, so the plugin is uninstallable by name.
- **Local sources are keyed on `path` alone.** `{"type": "local", "path": …}`,
  `{"source": "local", …}`, a bare string, an object with **no** discriminator, and one
  with a **bogus** `type` all install identically. Requiring a discriminator is a false
  positive. A `url` is what makes an entry remote, and its own `path` then names a
  subdirectory of the clone.
- **`sha`**: nothing is validated at add or list time. The installer accepts 40 or 64
  hex, **case-insensitively**; a short ref or a branch name is refused, and an absent
  `sha` degrades to an unpinned `git clone`. The upstream `validate-catalog.py` requires
  lowercase 40-hex, which is stricter than the runtime.
- **`plugin-index.json`** is the sole source of the pre-install component listing, and
  it must sit beside its catalog. For a url source it is gated on `sha` equality with
  the catalog entry — drift silently blanks the listing. For a local source there is no
  `sha` to gate on, so a stale index is displayed while the plugin on disk disagrees. An
  index entry with no catalog entry, and a malformed index, are both ignored silently.
- **Plugin hooks are a different loader from the project layer's.** `grok inspect
  --json` reports one opaque entry for a plugin's `hooks/hooks.json` whether the file is
  valid, empty or unparseable, so the failure matrix above is **not** evidence about it.
  That is why plugin hooks attach as `GrokPluginHooksBlock`, a sibling of
  `GrokHooksBlock` rather than a subclass, and `grok-hooks-valid` never sees them.
  `hooks-dangerous` and `hooks-prohibited` read the shared `HooksBlock` base and do.

### skillsaw code for this
- Vocabulary (marker names, both resolution orders, the name and `sha` patterns, the
  component table, the manifest readers) — `src/skillsaw/formats/grok.py`.
- Discovery — `src/skillsaw/discovery/grok.py`, state-free: catalog enumeration, local
  sources, plugin directories. The `.grok-plugin` directories come from the one
  repository walk (`PLUGIN_MARKER_DIR_NAMES` in `discovery/detect.py`), so a plugin or a
  catalog in a monorepo package is found without a second traversal.
- Caching and the `--type` gate — `RepositoryGrokMixin` in
  `src/skillsaw/repository_grok.py`, mixed into `RepositoryContext`. It lives outside
  `context.py` because `tests/test_module_layering.py` caps that file at 900 lines.
- Ownership — one branch in `RepositoryContext.provenance()`
  (`src/skillsaw/repository_provenance.py`) adding `"grok"`, plus `grok_only`,
  `is_grok_only_plugin` and `in_grok_only_plugin` for conditional strictness.
- Lint tree — `GrokPluginNode`, `GrokPluginConfigNode`, `GrokMarketplaceConfigNode` and
  `GrokMarketplaceIndexNode` in `src/skillsaw/lint_target.py`; `GrokPluginHooksBlock`,
  `GrokMcpBlock`, `GrokInlineHooksBlock` and `GrokInlineMcpBlock` in
  `src/skillsaw/blocks/json_config.py`; all attached in the one plugin pass in
  `src/skillsaw/lint_tree.py`. A dual-manifest directory keeps the class the other
  ecosystem's branch already attached, so one file never gets two blocks.
- Types — `RepositoryType.GROK_PLUGIN` and `GROK_MARKETPLACE` in
  `src/skillsaw/repository_types.py`, both in `SKILL_REPO_TYPES` and neither in
  `TOOL_REPO_TYPES`.

There is deliberately no Grok install-root helper. Codex has one because
`.codex/plugins/` holds plugins a developer installed into their own checkout, which
autofix must not rewrite. Grok's repository-resident location, `.grok/plugins/`, is
documented as "Project, shared through version control" — authored content — and its
auto-trusted counterpart `~/.grok/plugins/` is never in a checkout.

## skillsaw rules that map
- Hooks — `src/skillsaw/rules/builtin/grok/`: `grok-hooks-valid`.
- Subagents — `src/skillsaw/rules/builtin/grok/`: `grok-agent-valid`, the `name` and
  `description` Grok's loader registers a `.grok/agents/*.md` by. An empty value
  satisfies it; presence is the whole test.
- Plugin manifests — `grok-plugin-json-valid` (ERROR): invalid JSON and a `name` that
  is missing, non-string, empty or outside `PLUGIN_NAME_RE`, each of which makes Grok
  skip the whole directory. Component paths that escape or do not exist, and an
  override replacing the conventional directory, are WARNING; a non-semver `version`
  and an absent `description` are INFO. It reports no unknown key, no name/directory
  disagreement, and no bare string where an array is allowed.
- Plugin directories — `grok-plugin-structure` (WARNING): no manifest and none of
  `skills/<n>/SKILL.md`, `agents/*.md`, `hooks/hooks.json` or `.mcp.json`, which is
  what `grok plugin install` refuses. One INFO for a manifest-less directory a catalog
  addresses by name, since it installs as `<dir>-<hash>`.
- Catalogs — `grok-marketplace-json-valid` (ERROR): the whole-catalog defects (invalid
  JSON, a non-object root, a missing or non-array `plugins`) and the entry defects that
  drop a plugin silently, plus the `sha` contract. The url `path` shape and a source
  object naming neither a `path` nor a `url` are WARNING, an uppercase `sha` is INFO.
  It never requires a source discriminator or a top-level catalog `name`.
- Index parity — `grok-marketplace-index-parity` (WARNING): one consolidated finding
  per `plugin-index.json` for name, `sha` and (local sources only) skill drift, one for
  a malformed index, and one for an index Grok never reads because it is not beside its
  catalog. Silent when there is no index.
- Vocabulary (events, aliases, handler fields, reserved env, failure scopes) — one
  module, `src/skillsaw/formats/grok.py`, so a behavior change is an edit there rather
  than a hunt through rule code.
- Detection — `src/skillsaw/discovery/detect.py` (`grok-project`: any of `rules/`,
  `skills/`, `agents/`, `commands/`, `hooks/`, `workflows/`, `roles/`, `personas/`,
  `config.toml`, `lsp.json` or `sandbox.toml` inside a `.grok/` — eleven entries in
  `_TOOL_EVIDENCE["grok-project"]`); `RepositoryType.GROK_PROJECT` in
  `src/skillsaw/repository_types.py` is what the rule gates on and what `Repo type:`
  reports.
- Skills — `.grok/skills` in `CONVENTIONAL_SKILL_DIRS`
  (`src/skillsaw/discovery/__init__.py`), which is what earns the whole skill rule set
  without a Grok rule.
- Lint tree nodes — `src/skillsaw/blocks/json_config.py` (`GrokHooksBlock`, a
  `HooksBlock` subclass so `hooks-dangerous` and `hooks-prohibited` scan it like every
  other host's hooks file; lenient JSON on purpose, because Grok's `serde_json` reader
  accepts a duplicate key and runs the file), `src/skillsaw/blocks/content.py`
  (`GrokRuleBlock`) and `src/skillsaw/blocks/frontmatter.py` (`GrokCommandBlock`,
  `GrokAgentBlock`), attached in `src/skillsaw/lint_tree.py`.
- The Rust-dialect matcher check is shared with Muse Code:
  `rust_matcher_error` in `src/skillsaw/rules/builtin/utils.py`.

## Sync notes
Hand-copied values and measured facts that drift — re-check each against the shipped
user guide, or re-verify empirically with the canary matrix above:
- `HOOK_EVENTS` (the 15 above) in `formats/grok.py`.
- `HOOK_EVENT_ALIASES` — 39 entries. The irregular one is `userPromptSubmit`, which
  Grok does *not* accept although every other camelCase spelling loads; verify a new
  alias rather than deriving it from a naming rule.
- `HOOK_HANDLER_TYPES` = `{"command", "http"}` and `HOOK_REQUIRED_FIELDS`, the field
  each type needs.
- `HANDLER_FIELDS` (the typed table) and `RESERVED_ENV_VARS`.
- `MATCHER_IGNORED_EVENTS` = `{"Stop", "UserPromptSubmit"}`.
- `WILDCARD_MATCHERS` = `{"", "*"}` — `*` is special-cased by Grok, not compiled.
- `REQUIRED_FIELDS` = `("name", "description")` in `rules/builtin/grok/agent_valid.py` —
  the keys Grok's subagent loader requires; an empty value still registers.
- `TIMEOUT_MAX` = `2**64 - 1` in `formats/grok.py`, the `u64` ceiling `timeout`
  deserializes into. It has to track Grok's timeout type: widen or narrow the field
  upstream and the boundary this reports moves with it.
- `PLUGIN_NAME_RE` = `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$` and
  `PLUGIN_NAME_MAX_LENGTH` = 64 in `formats/grok.py`, measured boundary by boundary:
  `-lead`, `trail-`, `UPPER`, `under_score`, `dot.name`, `""` and 65 characters are
  rejected; `123`, `a`, `a--b` and 64 characters are accepted. The loader's own message
  is what `grok-plugin-json-valid` quotes.
- `SHA_RE` and `SHA_LENGTHS` = `{40, 64}` in `formats/grok.py`. The catalog loader
  validates nothing at add or list time; rejection happens at install and is
  **case-insensitive**, so 40 lowercase is the upstream validator's rule and gets its
  own INFO. An absent `sha` degrades to an unpinned `git clone`.
- **Duplicate resolved names are an install failure**, which is what makes the
  duplicate check in `grok-marketplace-json-valid` an ERROR. Re-verify by installing
  from a catalog with two entries resolving to one manifest name; the measured message
  is `Multiple marketplaces provide a plugin named "canary"`.
- `SINGLE_PATH_FIELDS` = `{"hooks", "mcpServers"}` in `formats/grok.py`: each takes one
  path or one inline object. Measured, `"hooks": ["hooks/hooks.json"]` loaded as an
  empty inline document (`hookType: "inline"`, no target) where the bare string loaded
  the file, and `"mcpServers": ["servers.json"]` loaded no servers. Re-verify with
  `grok inspect --json` if the manifest type changes upstream.
- The component set that makes a manifest-less directory installable —
  `skills/<n>/SKILL.md`, `agents/*.md`, `hooks/hooks.json`, `.mcp.json` — in
  `_installable` in `rules/builtin/grok/plugin_structure.py`. `commands/` alone and
  `.lsp.json` alone are discovered and then refused by `grok plugin install`, which is
  the asymmetry to re-verify if the installer changes.
- **Replace, not extend.** A manifest `skills`/`commands`/`agents` path replaces the
  conventional directory; the official `plugin_catalog.py` unions the two, so the two
  readers disagree and the binary is the one to follow. `COMPONENT_PATHS` in
  `formats/grok.py` records both, `grok-plugin-json-valid` warns on the loss, and
  the lint tree attaches both, so what an override drops is still linted.
  `grok-marketplace-index-parity` is the exception: it compares against a file the
  *generator* wrote, so it carries the union of both readings and reports drift only
  for a name neither produces.
- `rules/`, `commands/`, `agents/` and `hooks/` are read **flat**; `skills/` is walked
  recursively. Re-verify with `grok inspect --json` on a nested file. A change here is
  silent under-attachment — skillsaw stops linting real context and reports nothing —
  not a false positive, so nothing fails to draw attention to it.
- `.grok/settings.json` is **reserved**. superagent-ai/grok-cli is a second reader of a
  project `.grok/`, and its hooks loader names a project-level `settings.json` there
  only to skip it. Never attach it and never make it detection evidence — it is not a
  surface Grok Build reads, and claiming it would claim another tool's state.

## Not covered yet
Deliberate gaps, each with the reason it is a separate piece of work:
- **`.lsp.json`** — no public schema, and no LSP entries in the official marketplace, so
  there is nothing to calibrate a rule against.
- **`.grok/config.toml`** — only `[mcp_servers]`, `[plugins]`, `[permission]` and
  `[mcp] max_output_bytes` are honored at project scope and everything else is silently
  ignored, which is a high-signal check. It needs a TOML parser, and `tomllib` is
  stdlib only from Python 3.11 while this project supports 3.9, so it carries a new
  conditional `tomli` dependency that should be argued on its own.
- **`.grok/lsp.json`, `.grok/sandbox.toml`, `.grok/roles/`, `.grok/personas/`,
  `.grok/workflows/*.rhai`** — no public schema, a TOML dependency, or a scripting
  language a regex would misread. Those five and `config.toml` are detection evidence
  today and nothing more: nothing parses or attaches them, so detection and attachment
  cannot disagree about them.
