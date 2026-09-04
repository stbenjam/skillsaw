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

Everything skillsaw asserts was verified against `agy` 1.1.25 rather than taken from
the docs. Method: an isolated `HOME` (the real `~/.gemini` never read or written),
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
  problem drops that server *silently*: non-object server, non-string `env` values,
  non-string `args` elements, non-string `serverUrl`, bad `disabledTools` type, an
  `authProviderType` other than `"google_credentials"`. `serverUrl` wins over
  `command`; `url` + `type` is a third shape; a server with neither loads without
  complaint. `disabled` is the toggle — `enabled` is not a key. Credential-bearing
  fields: `env`, `headers`, `clientId`/`clientSecret`, `oauth.clientId`/`clientSecret`.
- **Plugin manifest**: `plugins/<n>/plugin.json`, direct children only, parsed by
  **protojson** with four meaningful fields — `name`, `description`, `disabled`,
  `logo`. Every other key including `$schema`, `version` and `author` is discarded and
  the plugin loads. `name` is optional for discovery (it defaults to the directory
  name) and required by `agy plugin validate` / `install`, which also enforce
  `[A-Za-z0-9_-]` with no leading dot. A duplicate `name` key is an error. There is **no
  published plugin schema**: `https://antigravity.google/schemas/v1/plugin.json` is 404.
- **`agy` claims Agent Plugins manifests.** A `plugin.json` carrying the portable
  `$schema` under `.agents/plugins/` is loaded unchanged, so a directory can belong to
  both ecosystems.
- **Registries**: `{"entries": [{"path", "include_only", "exclude"}], "inherits": […]}`.
  `path` is absolute, `~/`-relative, or repo-root-relative and must name the item
  directory itself. A non-object root logs one `Failed to load JSON config file` line
  and skips the file.

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
- `MCP_CREDENTIAL_MAPS` and `MCP_CREDENTIAL_KEY_ALIASES`. The alias table exists only
  so the shared credential-*name* detector sees `clientSecret` as `client_secret`.
- The one accepted `authProviderType` value, in
  `rules/builtin/antigravity/mcp_valid.py`.

## Not covered yet
- Workspace and plugin `mcp_config.json` **loading** is unobserved. `agy mcp list` and
  `agy mcp add` read and write `~/.gemini/config/mcp_config.json` only; the shape
  matrix was obtained at that global path, which exercises the same parser. The public
  doc names the workspace location; the embedded doc does not.
- Skill discovery has no offline listing command, so `<root>/skills/<n>/SKILL.md`
  produced no output and no diagnostic.
- `skills.json` and `workflows.json` could not be triggered as loaders.
- Everything after load: dispatch, `matcher` semantics, the runtime effect of a
  hook-level `enabled: false`, hook stdout contracts, and the runtime string
  `prompt hooks are not supported for the PostToolUse event`.
- The 12,000-character cap the rules-and-workflows page publishes for a rules file is
  not implemented as a rule.
