## Why

Command file names are used as identifiers in invocation syntax
(`/plugin:command-name`). Non-kebab-case names break conventions and
may not be recognized by all runtimes.

## Examples

**Bad:**

```
commands/deployStaging.md
commands/Run_Tests.md
```

**Good:**

```
commands/deploy-staging.md
commands/run-tests.md
```

## How to fix

Rename the command file to use kebab-case (lowercase letters and
hyphens only). `skillsaw fix` can suggest the correct filename.

## Codex plugins

This is a Claude-format convention. A directory claimed only by OpenAI
Codex — a `.codex-plugin/plugin.json`, or a local-source listing in a
Codex catalog, with no `.claude-plugin` marker or Claude marketplace
listing — is exempt: Claude never loads it, so Claude command naming conventions do not apply to its commands/. A dual-manifest
directory keeps this check, and the ecosystem-neutral content and
security rules read every plugin's files regardless of provenance.
