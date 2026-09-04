# Google Antigravity

<!-- Repo-root-relative src/... paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Google Antigravity is Google's agentic coding platform; its CLI is `agy`. A checkout
configures it through a *customization root* — `.agents/`, `.agent/`, `_agents/` or
`_agent/`. Much of that layer is shared convention other tools read too — portable
Agent Skills under `skills/`, `AGENTS.md`, the committed `.agents/memory/` notes — so
what skillsaw validates that is Antigravity's alone is its lifecycle hooks, its MCP
configuration, its plugin manifests, and its customization registries.

## Upstream source(s)
- The documentation `agy` embeds verbatim as string blobs: `# Lifecycle Hooks
  (hooks.json)`, `# MCP Servers (mcp_config.json)`, `# Plugins`, `# JSON Configuration
  Files`, `# Antigravity Customization System Guide`, `# Google Antigravity (AGY) Guide
  & Sitemap`. Extract with `strings` on the binary.
- https://antigravity.google/docs/mcp/ — the workspace `mcp_config.json` location, the
  property list, and the `oauth` example. Note the two vendor sources disagree: the
  embedded doc names only `~/.gemini/config/mcp_config.json` and
  `plugins/<name>/mcp_config.json`.
- https://antigravity.google/docs/hooks/ — the events and the `matcher` spellings.

The initial loader checks used `agy` 1.1.25; additional checks with 1.1.26 are
recorded below. Method: an isolated `HOME` (the real `~/.gemini` never read or written),
outbound proxies pointed at a dead port, one fixture per case, read back from
`agy agents`, `agy mcp list`, `agy plugin validate`, `agy plugin install` and the
`--log-file` diagnostics (`hooks_manager.go:33`, `discovery.go:551`, `plugins.go:117`).

```bash
HOME="$SCRATCH/fakehome" HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 \
  timeout 60 agy --add-dir "$WORKSPACE" --log-file "$SCRATCH/agy.log" agents
```

**`--add-dir` is not optional.** `agy agents` and the hooks counter report workspace
customizations only when the workspace is passed with `--add-dir`; being the CWD is not
enough, and a matrix run without it silently reports the global scope only. `agy
--print` requires OAuth and blocks, so **no model turn was ever run**: every hooks
finding is about *loading*, and matcher semantics, `enabled: false` at run time, hook
stdout contracts and `decision` handling are all unobserved. Re-run the matrix before
changing a rule here.

## What to check
- **Customization roots** (four): `.agents/`, `.agent/`, `_agents/`, `_agent/`.
  Discovery walks **up** from the entry directory to the repository root and unions
  every root on the way; it never descends. `.git` is not required. Repo-root
  `hooks.json`, `<ws>/.gemini/` and `<ws>/.antigravity/` are not read. `ANTIGRAVITY.md`
  does not exist — zero occurrences in the binary.
- **Per root**: `hooks.json`, `mcp_config.json`, `rules/**/*.md`, `agents/<n>.md`,
  `skills/<n>/SKILL.md`, `plugins/<n>/`, and the registries `agents.json`,
  `plugins.json`, `skills.json`, `workflows.json`.
- **Hooks failure scope** is the thing to get right. **Every** load-time rejection is
  *file-scoped and non-fatal*: the file contributes zero hooks, one `failed to parse
  hooks.json at <path>: <err>` is logged, and `agy` still exits 0. There is no
  entry-scoped rejection and no startup abort.
  - Document shape: `{hookName: {enabled?, Event: [...]}}`. Every top-level key is a
    hook *name*, so `"enabled": false` at the top level is a hard parse error, not a
    switch.
  - `PreToolUse` / `PostToolUse` hold `{matcher, hooks: [handler, ...]}` groups;
    `PreInvocation`, `PostInvocation`, `Stop` and **`SessionStart`** hold flat handler
    lists. `SessionStart` is undocumented and real. **The event picks the shape, not
    the entry's keys**: a `hooks` key on a flat event is an ignored handler key, so
    `{"Stop": [{"command": "…", "hooks": []}]}` runs that `command`. Reading the key
    instead of the event makes it an empty group and hides the command from the
    security rules.
  - **Event keys bind case-insensitively** — `pretooluse` reaches `PreToolUse`. An
    unknown event key is silently ignored.
  - Handler types: `command` (the default when `type` is absent or `""`) and `prompt`.
    Any other value fails the file, case-sensitively. A command hook may not carry
    `prompt` or `model`; a prompt hook may not carry `command`.
  - Handler keys: `type`, `command`, `prompt`, `model`, `timeout`. Anything else is
    ignored. `timeout` is an **int32**: `0` and negatives load, while a float, a
    string, or an integer past either end of `-2147483648`…`2147483647` kills the
    file. Group keys: `matcher`, `hooks`; anything else ignored.
  - `matcher` must be a string and is **never compiled at load time** — `"[unclosed"`
    loads clean. `""` and `"*"` are documented catch-alls. The engine is unproven: the
    binary is Go and carries `regexp/syntax` types, which implies RE2.
  - Missing `command` and empty `command` both load.
- **MCP shape**: root must be `{"mcpServers": {…}}`; a bare server map is silently
  ignored. A syntax error or non-object root is **exit 1**. Any per-server shape
  problem drops that server *silently*: non-object server, non-string/non-null `env` values
  or `args` elements, non-string/non-null `command`, `url`, `serverUrl` or `cwd`,
  bad `disabledTools` type, an
  `authProviderType` other than `"google_credentials"`. `serverUrl` wins over
  `command`; `url` + `type` is a third shape; a server with neither loads without
  complaint. `disabled` is the toggle — `enabled` is not a key. Credential-bearing
  fields: `env`, `headers`, `clientId`/`clientSecret`, `oauth.clientId`/`clientSecret`.
  Null `disabledTools` elements are accepted. A mistyped `type` is also tolerated.
- **Plugin manifest**: `plugins/<n>/plugin.json`, direct children only, parsed by
  **protojson** with four meaningful fields — `name`, `description`, `disabled`,
  `logo`. Every other key including `$schema`, `version` and `author` is discarded and
  the plugin loads. `name` is optional for discovery (it defaults to the directory
  name) and required by `agy plugin validate` / `install`, which also enforce
  `[A-Za-z0-9_-]` with no leading dot. A duplicate `name` key is an error. The manifest
  schema **is published**, inline under "Full JSON Schema" at
  `https://antigravity.google/docs/cli/plugins/` (read 2026-09-04): `name` required
  with pattern `^[a-zA-Z0-9-_]+$`, `description` optional, `additionalProperties:
  false`. The `$schema` URL the page tells authors to write —
  `https://antigravity.google/schemas/v1/plugin.json` — is 404, so nothing can
  dereference it. The published schema is narrower than the loader: `disabled` and
  `logo` load and are absent from it, and `additionalProperties: false` is not enforced
  at load time, so the rule stays on the measured protojson field set.
- **`agy` claims Agent Plugins manifests.** A `plugin.json` carrying the portable
  `$schema` under `.agents/plugins/` is loaded unchanged, so a directory can belong to
  both ecosystems.
- **Registries**: `{"entries": [{"path", "include_only", "exclude"}], "inherits": […]}`.
  `path` is absolute, `~/`-relative, or repo-root-relative. A non-object root logs one
  `Failed to load JSON config file` line and skips the file.
  - `agents.json`: `path` names the directory holding the agent `.md` files.
  - `plugins.json`: `path` names a plugin directory *or* a container of them; both
    load. `inherits` names another registry **file** — a directory there loads
    nothing. `include_only` / `exclude` filter by directory name.
  - skillsaw resolves both into the lint tree (`resolve_registry_entries`): a
    `plugins.json` target joins the provenance claim set so the single plugin pass
    builds its container, and an `agents.json` target's `*.md` attaches as agent
    prose. `include_only` / `exclude` are ignored for what is linted, on the same
    policy as a hook-level `"enabled": false`.

## skillsaw rules that map
- Hooks, MCP, manifest, registries — `src/skillsaw/rules/builtin/antigravity/`:
  `antigravity-hooks-valid`, `antigravity-mcp-valid`, `antigravity-plugin-json-valid`,
  `antigravity-config-json-valid` (opt-in).
- Vocabulary (roots, filenames, events, handler fields, manifest fields) — one module,
  `src/skillsaw/formats/antigravity.py`, constants only, so a behavior change is an
  edit there rather than a hunt through rule code.
- Discovery — `src/skillsaw/discovery/antigravity.py` (state-free) and
  `src/skillsaw/repository_antigravity.py` (the caching and `--type` gate).
- Detection — `src/skillsaw/discovery/detect.py` (`antigravity_marker()`);
  `RepositoryType.ANTIGRAVITY` and `ANTIGRAVITY_PLUGIN` in
  `src/skillsaw/repository_types.py`.
- Lint tree nodes — `src/skillsaw/blocks/json_config.py`
  (`AntigravityHooksBlock`, `AntigravityMcpBlock`, `AntigravityConfigBlock`),
  `src/skillsaw/blocks/content.py` (`AntigravityRuleBlock`),
  `src/skillsaw/blocks/frontmatter.py` (`AntigravityAgentBlock`), and
  `src/skillsaw/lint_target.py` (`AntigravityPluginNode`,
  `AntigravityPluginConfigNode`), attached in `src/skillsaw/lint_tree.py`.

## Measurements
The original loader measurements used `agy` 1.1.25, in an
isolated `HOME` with outbound proxies pointed at a dead port. The observables are the
`--log-file` counter `loaded N named hooks from M hooks.json file(s)`, its
`Failed to load JSON config file` / `failed to parse` lines, `agy mcp list`,
`agy agents` and `agy plugin validate`. Re-run any of these against a newer `agy`
before trusting the rule that rests on it.

| # | Date | Question | Observable | Result |
| --- | --- | --- | --- | --- |
| 1 | 2026-09-03 | Are duplicate object keys a defect? | hook counter, `agy mcp list`, `agy agents` | Repeated keys load in hooks, MCP and registries. Wrappers, names and scalar fields take the last value; repeated MCP maps are the exception measured below. `plugin.json` is the exception (protojson: `proto: duplicate field`). |
| 2 | 2026-09-04 | Do registry `entries` name customization that really loads? | `agy agents` | Yes. A `plugins.json` path may be one plugin directory or a container of them; `inherits` follows a registry *file* only; `include_only`/`exclude` filter by directory name; a path outside the workspace loads nothing. |
| 3 | 2026-09-04 | Is a top-level `enabled` a switch? Is `null` a defect? Do foreign shapes load? | hook counter, `agy mcp list`, `agy plugin validate` | `enabled` is an ordinary hook name — a non-null, non-object value there kills the file. Null is accepted at the measured placements; typed-field defaults and named map entries differ. A `hooks` object beside a numeric `version` fails the document; beside nothing it loads one inert hook named `hooks`. |
| 4 | 2026-09-04 | Is `""` the key's absence too? | hook counter, `agy mcp list`, `agy agents` | For **string** fields yes — `prompt`, `model`, `command`, `type`, `matcher`, a hook name, and `plugin.json`'s `name` all read as absent. Not for typed fields: `timeout: ""` and `disabled: ""` fail the document, and `authProviderType: ""` drops the server. A null `env` value or `args` element loads; `command: ""` loads a server that starts nothing. |

### Rechecked with agy 1.1.26 (2026-09-04)

The following cases were run again with an isolated home and no model turn:

| Input | Observable | Result |
| --- | --- | --- |
| A string `$schema` or `description` beside a valid named hook | `hooks_manager.go` parse error and count | `cannot unmarshal string into ... JSONHookSpec`; zero hooks loaded. |
| A top-level `enabled: true` beside a hook called `hooks` | Same log and count | Boolean unmarshal error; zero hooks loaded. |
| A null sibling beside a valid hook called `hooks` | Named-hook count | Two named hooks loaded, with no parse error; null is accepted. |
| `disabledTools: ["write_query", null]` | `agy mcp list` | The server is listed as enabled. |
| A numeric `command`, `url`, `serverUrl` or `cwd`, each on its own server | `agy mcp list`, with a valid control server | Each mistyped server is absent; the control remains listed. |
| `type: 42` beside a valid `command` | `agy mcp list` | The server remains listed. |
| A UTF-8 BOM before `mcp_config.json` | `agy mcp list` | Exit 1: invalid character `\\ufeff` looking for beginning of value. |
| A UTF-8 BOM before `hooks.json`, `plugins.json` or `plugin.json` | `agy agents` and debug logs | Each file is rejected: hooks load zero, the registry logs a JSON load error, and the manifest logs a protojson syntax error. |
| Both nonempty `serverUrl` and `url` | `agy mcp list` | The listed endpoint is `serverUrl`. Empty/null `serverUrl` leaves a command server unchanged. |
| Repeated `env`, `headers` or `oauth` objects | `agy mcp disable probe`, then read the isolated config it rewrites | Object members merge. An empty second object preserves earlier members; null clears the map. The probe used ordinary `COLOR` and `X-Color` strings, not credentials. |
| Repeated `mcpServers` wrapper or server name | Same isolated rewrite; `agy mcp list` | The second object replaces the first, including servers named `env`, `headers` or `oauth`. These are not merged maps. |

These are loader observations. They do not demonstrate hook dispatch or MCP
connections. Shared-file scanner tests separately verify that commands and
prompts remain visible once when several hosts read the same file.

## Loader versus validate
`agy plugin validate` and the loader read `plugin.json` with different parsers, and they
disagree. Validate uses `encoding/json` — it prints `[ok]` for `{"disabled": ""}` and
reports `cannot unmarshal number into Go struct field .name of type string` for a
mistyped name. The loader uses protojson, refuses `{"disabled": ""}` with
`invalid value for bool field disabled`, and does not load the plugin's agents.

The loader decides whether the directory is a plugin at all, so it is what the rules
follow. Check a manifest claim against `agy agents` and the `plugins.go` log lines, not
against `agy plugin validate` alone.

## Corpus survey
Earlier review sampling reported `27 of 30` repositories with `.agents/rules`
without an Antigravity file, `10 of 74` `.agents/hooks.json` files in another host's
shape, and `7 of 74` (17 commands) writing a flat event in the grouped shape. Those come from the review panel's GitHub sampling on **2026-09-04** and are
not reproduced in this repository: they were the evidence for a design decision, not a
fixture. Re-sample before relying on any of them again; the decisions they justified
stand on the `agy` measurements above.

## Sync notes
Hand-copied value sets that drift — re-check each against a fresh `agy`, not against
the docs:
- `ANTIGRAVITY_CONFIG_DIR_NAMES` (four roots) and `REGISTRY_FILENAMES` in
  `formats/antigravity.py`. `rules.json` exists as a literal in the binary but no
  loader was reached for it; `agy agents` queries only the agents and plugins kinds.
- `TOOL_HOOK_EVENTS` / `FLAT_HOOK_EVENTS`, `HOOK_HANDLER_TYPES`, `HOOK_HANDLER_KEYS`,
  `HOOK_GROUP_KEYS`. Probe each by giving the key a deliberately wrong type and reading
  the Go unmarshal error back — it names the struct field and its type.
- `PLUGIN_MESSAGE_FIELDS`. Probe the same way; a protojson error reads
  `proto: (line 1:9): invalid value for string field name: 42`.
- `MCP_STRING_FIELDS` (`command`, `url`, `serverUrl`, `cwd`); unlike these,
  a mistyped `type` is tolerated.
- `MCP_CREDENTIAL_MAPS` and `MCP_CREDENTIAL_KEY_ALIASES`. The alias table exists only
  so the shared credential-*name* detector sees `clientSecret` as `client_secret`.
- The one accepted `authProviderType` value, in
  `rules/builtin/antigravity/mcp_valid.py`.
- `EXCLUSIVE_ROOT_NAMES`. `.agent/` alone takes the wide detection predicate, so a
  populated `.agent/rules/` types a repository `antigravity` even when it configures
  several tools. Harmless — the type only switches on rules that need a target, and
  every Antigravity block attaches under a dot root regardless of detection — but it is
  the one place a shared checkout can pick the type up from prose alone.

## Not covered yet
- Workspace and plugin `mcp_config.json` **loading** is unobserved. `agy mcp list` and
  `agy mcp add` read and write `~/.gemini/config/mcp_config.json` only; the shape
  matrix was obtained at that global path, which exercises the same parser. The public
  doc names the workspace location; the embedded doc does not.
- Skill discovery has no offline listing command, so `<root>/skills/<n>/SKILL.md`
  produced no output and no diagnostic.
- `skills.json` and `workflows.json` could not be triggered as loaders, so the lint
  tree resolves neither registry's `entries` — only `agents.json` and `plugins.json`,
  both measured end to end.
- Everything after load: dispatch, `matcher` semantics, the runtime effect of a
  hook-level `enabled: false`, hook stdout contracts, and the runtime string
  `prompt hooks are not supported for the PostToolUse event`.
- The 12,000-character cap the rules-and-workflows page publishes for a rules file is
  not implemented as a rule.
- **Description routing on the workspace `agents/` block.** Both `ANTIGRAVITY` and
  `ANTIGRAVITY_PLUGIN` are in `content-description-routing`'s `repo_types`, so the rule
  runs on a plugin's skills and on the prose the shared plugin pass attaches. What stays
  out is `AntigravityAgentBlock` — the workspace `<root>/agents/*.md` — which is absent
  from the rule's explicit traversal list. Deliberate, pending a measurement: the
  frontmatter contract for that file was not reachable offline, so there is no measured
  field to route on.
- **`<root>/workflows/` prose.** `workflows.json` is attached as a registry; the
  directory beside it is not walked, so `.agent/workflows/*.md` contributes no blocks.
  Both the file's role as a loader and the workflow files' own frontmatter are
  unmeasured.
