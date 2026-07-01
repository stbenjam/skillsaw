# skillsaw-example-plugin

A complete, minimal example of a **skillsaw rule plugin** — a pip-installable
package that adds lint rules to [skillsaw](https://github.com/stbenjam/skillsaw).
It packages the `no-todo-instructions` rule from the
[custom rules documentation](https://skillsaw.org/custom-rules/) so the same
rule can be shared across every repository in an organization instead of
being copied into each one.

See the [plugin documentation](https://skillsaw.org/plugins/) for the full
authoring guide.

## Layout

```
skillsaw-example-plugin/
├── pyproject.toml                        # entry point registration
├── src/
│   └── skillsaw_example_plugin/
│       ├── __init__.py                   # SKILLSAW_* declarations
│       ├── rules.py                      # the Rule subclass
│       ├── extensions.py                 # repo type + lint tree contributor
│       └── cli.py                        # optional: `skillsaw example` CLI
└── tests/
    ├── fixture/CLAUDE.md                 # realistic test fixture
    └── test_rules.py
```

The two pieces that make it a plugin:

1. **The entry point** in `pyproject.toml`:

   ```toml
   [project.entry-points."skillsaw.plugins"]
   example = "skillsaw_example_plugin"
   ```

2. **The declarations** in `src/skillsaw_example_plugin/__init__.py`:

   ```python
   SKILLSAW_RULES = [NoTodoInstructionsRule, AcmeConfigVersionRule]
   SKILLSAW_REPO_TYPES = [ACME_REPO_TYPE]
   SKILLSAW_TREE_CONTRIBUTORS = [contribute_acme_config]
   ```

`extensions.py` demonstrates the extension points with a fictional "ACME"
assistant: a `PluginRepoType` whose detector recognizes ACME repositories
(scoping `acme-config-version` to them and pulling `ACME.md` /
`.acme/rules/*.md` into content linting), and a tree contributor that
attaches `.acme/config.json` as a `JsonConfigBlock` for the rule to lint.

## Try it

```console
$ pip install ./examples/plugins/skillsaw-example-plugin
$ skillsaw plugins
Installed skillsaw plugins:

  example (skillsaw-example-plugin 0.1.0)
    source: skillsaw_example_plugin
    rules:
      no-todo-instructions — Instruction files should not contain TODO/FIXME comments

$ skillsaw lint            # the rule now runs automatically
$ skillsaw fix --rule no-todo-instructions   # deterministic autofix
$ skillsaw example rules   # dispatches to the skillsaw-example console script
```

Users configure the rule like any other, in `.skillsaw.yaml`:

```yaml
rules:
  no-todo-instructions:
    severity: error
    patterns: ["TODO", "FIXME", "HACK"]
```

## Run the tests

```console
$ python -m venv .venv && .venv/bin/pip install -e . pytest
$ .venv/bin/pytest
```
