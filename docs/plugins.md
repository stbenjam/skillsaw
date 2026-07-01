# Rule Plugins

Rule plugins are pip-installable Python packages that add lint rules to
skillsaw. Where [custom rules](custom-rules.md) live as `.py` files inside one
repository, a plugin packages the same kind of rules for reuse: publish it to
PyPI once, and every repository whose environment installs it gets the rules
automatically — no `.skillsaw.yaml` changes needed.

!!! note "Naming: two kinds of 'plugin'"
    A **rule plugin** extends the skillsaw linter itself. It is unrelated to
    the Claude Code plugins (`.claude-plugin/plugin.json`) that skillsaw
    *lints* — those are content skillsaw checks, not extensions to skillsaw.

## Using plugins

Install a plugin into the same environment as skillsaw and its rules are
discovered automatically on the next run:

```console
$ pip install skillsaw-example-plugin
$ skillsaw lint
```

List what's installed, including each plugin's rules and any load failures:

```console
$ skillsaw plugins
Installed skillsaw plugins:

  example (skillsaw-example-plugin 0.1.0)
    source: skillsaw_example_plugin
    rules:
      no-todo-instructions — Instruction files should not contain TODO/FIXME comments
```

Plugin rules behave exactly like builtin rules: they appear in
`skillsaw list-rules` and `skillsaw explain <rule-id>`, they are configured
per rule ID in `.skillsaw.yaml`, they can be selected with `--rule` or
skipped with `--skip-rule`, and their violations participate in baselines,
suppressions, excludes, and the grade. Violations report their origin in the
`source` field (`plugin:<name>`) in JSON output.

### Configuring plugin rules

Use the normal `rules:` section, keyed by rule ID:

```yaml
rules:
  no-todo-instructions:
    enabled: true
    severity: error
    patterns: ["TODO", "FIXME", "HACK"]
```

### Disabling plugins

Turn off a specific plugin, or all of them, in `.skillsaw.yaml`:

```yaml
plugins:
  disable: [example]     # skip specific plugins by name
```

```yaml
plugins: false           # shorthand: skip all rule plugins
```

Or skip all plugins for a single run:

```console
$ skillsaw lint --no-plugins
```

### Plugin subcommands

A plugin can also ship a CLI, reachable as a skillsaw subcommand. When a
plugin package installs a console script named `skillsaw-<name>` (matching
its entry point name), `skillsaw <name> [args...]` runs that executable with
the remaining arguments forwarded verbatim, git-style — its exit code becomes
skillsaw's exit code:

```console
$ skillsaw typos accept        # runs: skillsaw-typos accept
```

Dispatch rules:

- Builtin subcommands always win — a plugin cannot shadow `lint`, `fix`,
  `baseline`, etc.
- Only **registered** plugins are eligible: the name must match an installed
  `skillsaw.plugins` entry point. A stray `skillsaw-foo` executable on PATH
  is never executed. The check reads package metadata only, so no plugin
  code is imported to dispatch.
- If the name also matches an existing file or directory, the plugin command
  still wins and a note is printed; use `skillsaw lint <path>` to lint the
  path instead.

`skillsaw plugins` shows each plugin's command when one is installed.

### Broken plugins

A plugin that fails to import (or whose rules crash on construction) never
aborts the lint. skillsaw reports a `plugin-load-error` violation naming the
plugin and continues with the remaining rules:

```
✗ ERROR: Plugin 'acme' (skillsaw_acme) failed to load: ImportError: ...
```

Uninstall the package or disable the plugin to clear the error.

### Security

Installing a plugin executes its code with your privileges — the same trust
decision as installing any Python package. Review plugins as you would any
dependency. `--no-plugins` exists for locked-down CI runs, mirroring
`--no-custom-rules`.

## Writing a plugin

The fastest path: point your AI coding assistant at the
`skillsaw-create-plugin` skill in the
[skillsaw repo](https://github.com/stbenjam/skillsaw/tree/main/skills), or
copy the complete working example in
[`examples/plugins/skillsaw-example-plugin/`](https://github.com/stbenjam/skillsaw/tree/main/examples/plugins/skillsaw-example-plugin).
The manual version follows.

### 1. Package layout

```
skillsaw-acme-rules/
├── pyproject.toml
├── README.md
├── src/
│   └── skillsaw_acme_rules/
│       ├── __init__.py
│       └── rules.py
└── tests/
    ├── fixture/CLAUDE.md
    └── test_rules.py
```

Name the PyPI package `skillsaw-<name>` and the module `skillsaw_<name>` so
plugins are easy to find.

### 2. Register the entry point

skillsaw discovers plugins through the `skillsaw.plugins` entry point group:

```toml
[project]
name = "skillsaw-acme-rules"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = ["skillsaw>=0.14"]

[project.entry-points."skillsaw.plugins"]
acme = "skillsaw_acme_rules"
```

The entry point *name* (`acme`) is the plugin's short name, shown by
`skillsaw plugins` and used in `plugins: {disable: [...]}`. The *value* names
what provides the rules. Four forms are supported:

| Entry point value | Meaning |
|---|---|
| `skillsaw_acme_rules` | A module. Its `SKILLSAW_RULES` list is used when present; otherwise every concrete `Rule` subclass in the module is collected. |
| `skillsaw_acme_rules:RULES` | A list (or tuple) of Rule classes. |
| `skillsaw_acme_rules:MyRule` | A single Rule class. |
| `skillsaw_acme_rules:get_rules` | A callable returning an iterable of Rule classes. |

The module form with an explicit `SKILLSAW_RULES` declaration is the
recommended one:

```python
# src/skillsaw_acme_rules/__init__.py
from .rules import NoTodoInstructionsRule

SKILLSAW_RULES = [NoTodoInstructionsRule]
```

### 3. Write the rules

Plugin rules are ordinary `skillsaw.Rule` subclasses — the entire
[custom rules guide](custom-rules.md) applies verbatim: discover files
through the [lint tree](lint-tree.md), report line numbers, expose tunable
settings via `config_schema`, declare `repo_types` when the rule only applies
to certain repository types.

```python
from typing import List

from skillsaw import RepositoryContext, Rule, RuleViolation, Severity
from skillsaw.blocks import InstructionBlock


class NoTodoInstructionsRule(Rule):
    config_schema = {
        "patterns": {
            "type": "list",
            "default": ["TODO", "FIXME"],
            "description": "Patterns to flag in instruction files",
        },
    }

    @property
    def rule_id(self) -> str:
        return "no-todo-instructions"

    @property
    def description(self) -> str:
        return "Instruction files should not contain TODO/FIXME comments"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        patterns = self.config.get("patterns", self.config_schema["patterns"]["default"])
        for block in context.lint_tree.find(InstructionBlock):
            content = block.read_body(strip_code_blocks=False)
            if content is None:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if any(p in line for p in patterns):
                    violations.append(
                        self.violation(f"Found TODO/FIXME: {line.strip()}", block=block, line=i)
                    )
        return violations
```

Rule IDs must be unique across builtins and all installed plugins — a
colliding plugin rule is skipped with a warning, never silently shadowed.
Prefix rule IDs with something distinctive when in doubt (`acme-no-todo`).

Plugins can also ship **deterministic autofixes** by setting
`autofix_confidence` and overriding `fix()` — see the
[custom rules autofix example](custom-rules.md); it works unchanged in a
plugin. Fixes must be deterministic, scoped to the violation's exact lines,
and idempotent.

### Optional: ship a CLI

Add a console script named `skillsaw-<name>` and it becomes available as
`skillsaw <name> ...` (see [Plugin subcommands](#plugin-subcommands)):

```toml
[project.scripts]
skillsaw-acme = "skillsaw_acme_rules.cli:main"
```

The script owns its own argument parsing (`sys.argv[1:]` is whatever
followed `skillsaw acme`), and Python-based CLIs can `import skillsaw` to
reuse the config loader, lint tree, and baseline machinery. Typical use: an
`accept` command that appends currently-flagged values to the rule's
config in `.skillsaw.yaml`.

### 4. Test it

Test rules directly against a realistic fixture:

```python
from skillsaw.context import RepositoryContext
from skillsaw_acme_rules.rules import NoTodoInstructionsRule


def test_flags_todo(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# Project\n\nTODO: write docs\n")
    violations = NoTodoInstructionsRule().check(RepositoryContext(tmp_path))
    assert len(violations) == 1
```

When a test rewrites files and re-checks in the same process, call
`invalidate_read_caches()` (from `skillsaw.rules.builtin.utils`) first —
skillsaw caches file reads.

Then verify the packaging end-to-end:

```console
$ pip install -e .
$ skillsaw plugins            # plugin listed, no errors
$ skillsaw lint tests/fixture # rule fires with source plugin:acme
$ skillsaw lint --no-plugins  # rule disappears
```

### 5. Publish

```console
$ pip install build twine
$ python -m build
$ twine upload dist/*
```

For GitHub-hosted plugins, [trusted
publishing](https://docs.pypi.org/trusted-publishers/) from a release
workflow avoids long-lived PyPI tokens.

## How plugin rules are activated

Plugin rules use the same enablement logic as builtins, driven by the
class-level `Rule.default_enabled` (`True`, `False`, or `"auto"` — the base
class default):

1. An explicit `enabled: true/false` in the repo's `.skillsaw.yaml` wins.
2. With `default_enabled = "auto"`, rules declaring `repo_types`/`formats`
   only activate when the repository matches; unscoped auto rules run
   everywhere.
3. Set `default_enabled = False` for opt-in rules — they run only when the
   user configures them.

The [version pinning](configuration.md#version-pinning) gate compares a
rule's `since` field against the config's skillsaw `version`; plugin rules
keep the default `since = "0.1.0"` unless they deliberately opt into that
mechanism, so pinned configs still run them.
