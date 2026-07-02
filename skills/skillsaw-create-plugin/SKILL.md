---
name: skillsaw-create-plugin
description: "Create a skillsaw rule plugin — a pip-installable Python package that adds custom lint rules to skillsaw. Walks through scaffolding the package, writing rules against the lint tree, testing, and publishing to PyPI. Use when a user wants to share skillsaw rules across repositories or publish them for others."
compatibility: "Requires Python 3.9+ and skillsaw (pip install skillsaw). Publishing requires a PyPI account."
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Create Plugin

You are creating a **skillsaw rule plugin**: a Python package that adds lint
rules to [skillsaw](https://skillsaw.org). Once published to PyPI, anyone can
`pip install` it and skillsaw picks up the rules automatically — no config
required. This is the shareable alternative to per-repo `custom-rules:` files.

Note the terminology: a *skillsaw plugin* adds rules to the skillsaw linter
itself. It is unrelated to the Claude Code plugins that skillsaw lints.

Reference material while you work:

- Plugin guide: https://skillsaw.org/plugins/
- Rule-writing guide (lint tree, block types): https://skillsaw.org/custom-rules/
  and https://skillsaw.org/lint-tree/
- Complete working example: `examples/plugins/skillsaw-example-plugin/` in the
  [skillsaw repo](https://github.com/stbenjam/skillsaw)

Work through the steps in order. Communicate progress at each stage.

## Step 1: Gather requirements

Establish with the user:

1. **What should each rule check?** Get concrete examples of content that
   should pass and content that should fail.
2. **Rule IDs** — kebab-case, descriptive (e.g. `no-todo-instructions`).
   Run `skillsaw list-rules` and confirm no ID collides with a builtin rule
   or another installed plugin; skillsaw skips colliding plugin rules at load
   time.
3. **Severity** for each rule: `error` (must fix), `warning` (should fix), or
   `info` (advisory).
4. **Package name** — the convention is `skillsaw-<name>` on PyPI with module
   `skillsaw_<name>` (e.g. `skillsaw-acme-rules` / `skillsaw_acme_rules`).
5. **Tunable settings** — anything a user could reasonably want to adjust
   (patterns, thresholds, allowlists) belongs in `config_schema`, not
   hardcoded.

## Step 2: Scaffold the package

Create this layout:

```
skillsaw-<name>/
├── pyproject.toml
├── README.md
├── src/
│   └── skillsaw_<name>/
│       ├── __init__.py
│       └── rules.py
└── tests/
    ├── fixture/
    │   └── CLAUDE.md          # realistic fixture the rules run against
    └── test_rules.py
```

`pyproject.toml` — the entry point is what makes it a plugin:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "skillsaw-<name>"
version = "0.1.0"
description = "<one line: what the rules enforce>"
readme = "README.md"
requires-python = ">=3.9"
dependencies = ["skillsaw>=0.15"]

[project.entry-points."skillsaw.plugins"]
<name> = "skillsaw_<name>"

[tool.setuptools.packages.find]
where = ["src"]
```

The entry point name (left of `=`) is the plugin's short name — it appears in
`skillsaw plugins` output and in `plugins: {disable: [...]}` config. The value
points at the module that declares the rules.

`src/skillsaw_<name>/__init__.py`:

```python
from .rules import MyFirstRule

SKILLSAW_RULES = [MyFirstRule]
```

`SKILLSAW_RULES` is the explicit declaration skillsaw looks for. Every rule
class the plugin provides goes in this list.

## Step 3: Write the rules

Read `references/rule-authoring.md` in this skill's directory for the full
rule template, the requirements every rule must meet (lint tree discovery,
line numbers, `config_schema`, `repo_types`, `default_enabled`, YAML and
markdown parsing rules), and the deterministic-autofix template with its
scoping and idempotency requirements. Follow it exactly — the requirements
match what skillsaw's own review process enforces.

In short: each rule subclasses `skillsaw.Rule` in
`src/skillsaw_<name>/rules.py`, discovers files with
`context.lint_tree.find(NodeType)`, reports violations via
`self.violation(message, block=block, line=i)`, and exposes tunable settings
through `config_schema`.

### Optional capabilities

Read `references/extensions.md` when the plugin needs any of:

- **A CLI subcommand** — a `skillsaw-<name>` console script, dispatched as
  `skillsaw <name> [args...]` (registered plugins only).
- **A custom repository type** — `SKILLSAW_REPO_TYPES` declares a detector;
  detected types scope rules (string entries in `repo_types`) and pull the
  type's `content_paths` into content linting.
- **Lint tree nodes** — `SKILLSAW_TREE_CONTRIBUTORS` attaches plugin-defined
  blocks (`ContentBlock` for prose, `JsonConfigBlock` for machine config)
  that the plugin's rules find with `lint_tree.find()`.

## Step 4: Write tests

In `tests/test_rules.py`, cover at minimum:

1. The rule fires on the fixture with the expected message and line number.
2. Clean content produces no violations.
3. `config_schema` settings change behavior.
4. If the rule has autofix: the fix removes only the flagged lines, re-checking
   fixed content finds nothing, and fixing twice is a no-op. Call
   `invalidate_read_caches()` (from `skillsaw.rules.builtin.utils`) before
   re-checking — skillsaw caches file reads within a process.

Keep the fixture realistic — a CLAUDE.md that looks like a real project's,
not a one-line stub. See the example plugin's tests for the full pattern.

Run the tests:

```console
$ python -m venv .venv && .venv/bin/pip install -e . pytest
$ .venv/bin/pytest
```

## Step 5: Verify the plugin end-to-end

With the package installed (`pip install -e .` in the same environment as
skillsaw):

1. `skillsaw plugins` — the plugin appears with its rules and no ERROR lines.
2. `skillsaw lint <repo-with-violations>` — the rule fires, and the violation's
   `source` is `plugin:<name>` in `--format json` output.
3. `skillsaw explain <rule-id>` — shows the rule's description and config.
4. If it has autofix: `skillsaw fix --rule <rule-id>` applies it; a second run
   changes nothing.
5. `skillsaw lint --no-plugins` — the rule disappears (confirms it is loaded
   via the entry point, not some other path).

## Step 6: Write the README

Document in the plugin's README.md:

- What the rules enforce and why, with a violating and a passing example.
- Install instructions (`pip install skillsaw-<name>`).
- Each rule's ID, default severity, and `config_schema` options with a
  `.skillsaw.yaml` snippet.
- How to disable: `plugins: {disable: [<name>]}` or per-rule
  `enabled: false`.

## Step 7: Publish to PyPI

Ask the user whether to publish now. If yes:

```console
$ pip install build twine
$ python -m build
$ twine upload dist/*
```

For a GitHub-hosted plugin, offer to set up [trusted
publishing](https://docs.pypi.org/trusted-publishers/) with a release
workflow instead of long-lived API tokens. Pin action SHAs.

After publishing, confirm installation from PyPI works in a fresh
environment:

```console
$ pip install skillsaw-<name>
$ skillsaw plugins
```

## Step 8: Summary

Report to the user:

- Package name, module, and entry point name
- Rules created (ID, severity, autofix support, config options)
- Test results
- Where it was published (or how to publish later)
- How users consume it: `pip install skillsaw-<name>` next to skillsaw, then
  rules run automatically; configure per rule ID in `.skillsaw.yaml`
