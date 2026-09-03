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
