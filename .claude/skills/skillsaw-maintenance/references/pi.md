# Pi packages and project resources

## Upstream sources

- [Package documentation, v1.0.0](https://github.com/earendil-works/pi/blob/v1.0.0/packages/coding-agent/docs/packages.md)
- [Pinned loader source](https://github.com/earendil-works/pi/tree/v1.0.0/packages/coding-agent/src/core)
- [MCP configuration loader, v1.5.0](https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/src/extensions/mcp/config.ts)
- [MCP field validator, v1.5.0](https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/src/core/mcp-servers.ts)
- [Settings JSON Schema, v1.5.0](https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/schemas/settings.schema.json)

Compare `pi-manifest.ts`, `package-manager.ts`, and `skills.ts` against the
release tag when updating support. Pi now publishes a settings JSON Schema;
read it alongside `settings-manager.ts` when checking `.pi/settings.json`.

## Rules and discovery

The `pi-config-valid` rule checks resource arrays and local package selectors.
The `pi-skill-valid` rule validates native skill frontmatter and descriptions.
The opt-in `pi-resource-paths` rule checks assembled local paths.

Pi 0.99.0 introduced project `.pi/mcp.json`. It attaches as `PiMcpBlock`,
including nested projects, so shared credential and server policy checks run.
The opt-in `pi-mcp-valid` rule follows v1.5.0 field types and transport selection.
It remains opt-in pending the ten-repository accuracy survey.

MCP sync points: exposure names and the `codemode-deferred` alias; HTTP-first
selection when both command and URL are present; the unsupported SSE transport;
server namespace collisions after replacing hyphens with underscores; project
HTTP provider `auth` refusal; OAuth field types and callback-port bounds;
`oauth.clientRegistration` values and the `cimd` exclusion of `clientId` and
`clientName`; and `OVERRIDE_KEYS` with the `isOverride` test in `config.ts`.
A project entry without `command`, `url`, or `type` overrides the global
server of that name, so it may set only those keys. A valid override keeps
that global server, which Pi loads first, so its normalized namespace stays
taken: a project server differing only in `-`/`_`, or a second such override,
conflicts. Whether the global server exists is user configuration and stays
unchecked.
Pi 1.4 strips a leading UTF-8 BOM before parsing either `mcp.json`.
Pi 1.0 adds `oauth.authServerMetadataUrl`: a string naming an HTTPS metadata
document, with HTTP permitted on `localhost`, `127.0.0.1`, and `[::1]`.
The project `auth` guard also applies to stdio entries retaining any `url`
property and a JavaScript-truthy `auth` value.
The wrapper may be omitted, unknown fields are ignored, duplicate keys use the
last value, and empty commands pass field validation. Shared credentials include
`oauth.clientSecret`. Whole-value `!command` references are never executed and
still receive structured-token detection.

URI validation, including authorization metadata, OAuth callback URI
semantics, and the `cimd` callback path requirement, is deliberately deferred to Pi's WHATWG parser. User configuration,
MCP connections, and extension code remain outside static discovery.
Namespace checks admit stdio and ordinary ASCII DNS HTTP URLs without callback
or authorization metadata URIs; uncertain HTTP entries cannot reserve names
and create false conflicts.

## Sync notes

Check resource field names, remote source prefixes, conventional directories,
and the order of inclusion, exclusion, exact inclusion and exact exclusion.
Manifest globs discover paths; project wildcards filter literal roots. Project
prompt and theme autoload is shallow. Pi prefixes nested ignore patterns with
the declaring directory and matches overrides against absolute paths too;
compare those loader details before adopting generic gitignore semantics.

Pi skill names are optional. Flat Markdown needs a description to be a skill.
Unselected portable skills retain Agent Skills validation. Pi-only packages
receive shared prose checks but do not acquire Claude hooks/settings semantics.
Extensions remain data-only targets and remote packages are not installed.

## Architecture

Pi combines a packaging claim with a project tool layer. Its marker is a
`package.json` key or keyword, discovered by the shared repository scan rather
than a marker directory. Resource selection uses the scan mixin;
selected native skills use `PiSkillBlock`, while unselected portable skills
keep their Agent Skills role. A selected `SKILL.md` sits in a `PiSkillNode`
with its `references/*.md` attached through the tree builder's
`add_skill_references` seam, so the support prose and
`agentskill-unreferenced-files` cover it as they cover a portable skill;
the container is not a `SkillNode`, which keeps the `agentskill-*`
authoring rules off Pi's dialect. Report formatters use `skill_paths` and
`skill_count` so flat native skills are included in single- and multi-path
reports. Add `.pi/skills` through Pi's resource selection, not through the
unfiltered conventional skill directory lists.

## Pi 1.0.0 audit (2026-10-01)

Compared the tagged release to the pinned resource loader and v0.99.2 MCP
contract. `pi-manifest.ts`, `skills.ts`, `utils/frontmatter.ts`, and the MCP
configuration loader are unchanged. Resource selection, legacy skills migration,
and project autoload retain their checked contracts. The MCP field validator
adds only `oauth.authServerMetadataUrl`; its type is checked, while URI
semantics stay delegated as above.

The package manager adds built-in extension overrides such as `-builtin:mcp`,
already accepted as override patterns. Built-in extension execution, package
installation and dependency resolution remain outside static discovery.
Settings changes for fullscreen, quiet startup, default tools and codemode
are outside the resource-only `pi-config-valid` contract. OAuth credential
storage, issuer checks and incremental scope handling are runtime behavior.

## Pi 1.5.0 MCP audit (2026-11-06)

Compared the MCP loader and field validator at v1.5.0 against v1.0.0. The
loader adds project overrides and BOM stripping; the validator adds
`oauth.clientRegistration`. Moving the MCP extension into its own package
happened on main after v1.5.0; re-check source paths at the next tag.

## Pi 1.5.0 settings and changelog audit (2026-11-06)

Pi 1.5.0 publishes JSON Schemas for `settings.json`, `models.json`,
`keybindings.json`, and theme files under `https://pi.dev/schemas/`. The
opt-in `pi-settings-schema` rule validates project `.pi/settings.json`
against the tagged `settings.schema.json` bundled in
`src/skillsaw/schemas/pi/v1_5_0/`; its `SCHEMA-SOURCE.md` records the commit.
Re-copy the schema from the release tag, not pi.dev: on the audit date pi.dev
still served the 1.4.0 build. The settings loader validates nothing, so a
mistyped value is used as written. Resource keys stay with `pi-config-valid`.

`models.json` is read only from the user's agent directory
(`~/.pi/agent/models.json`), never from a project, so it stays out of scope.
Keybindings and themes have no project schema contract either.

`package.json#pi.changelogPath` is kept only when it is a string; `""`
disables the changelog. Pi shows the changelog only when the canonical path
is a file strictly inside the package root, and silently shows nothing
otherwise. `pi-config-valid` checks the type and `pi-resource-paths` checks
existence and containment.
