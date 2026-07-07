---
name: skillsaw-create-plugin
description: "Create a skillsaw rule plugin — a pip-installable Python package that adds custom lint rules to skillsaw. Walks through scaffolding the package, writing rules against the lint tree, testing, and publishing to PyPI. Use when a user wants to share skillsaw rules across repositories or publish them for others."
compatibility: "Requires Python 3.9+ and skillsaw (pip install skillsaw). Publishing requires a PyPI account."
license: Apache-2.0
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Create Plugin

Create a **skillsaw rule plugin**: a Python package that adds lint
rules to [skillsaw](https://skillsaw.org). Once you build and publish to PyPI, anyone can
`pip install` it and skillsaw picks up the rules automatically — no config
required. Prefer this to per-repo `custom-rules:` files when sharing rules across repos.

Keep the terminology straight: a *skillsaw plugin* adds rules to the skillsaw
linter itself. Never confuse it with the Claude Code plugins that skillsaw lints.

Review this reference material while you work:

- Read the plugin guide: https://skillsaw.org/plugins/
- Follow the rule-writing guide (lint tree, block types): https://skillsaw.org/custom-rules/ and https://skillsaw.org/lint-tree/
- Read the complete working example: `examples/plugins/skillsaw-example-plugin/` in the [skillsaw repo](https://github.com/stbenjam/skillsaw)

Follow each step in order, and keep the user updated on progress at each stage.

## Step 1: Gather requirements

Review the following with the user:

1. **What should each rule check?** Get concrete examples of content that should pass and content that should fail.
2. **Rule IDs** — use kebab-case, descriptive (e.g. `no-todo-instructions`).
   Run `skillsaw list-rules` and confirm no ID collides with a builtin rule or
   another installed plugin; skillsaw never loads colliding plugin rules.
3. **Severity** — set each rule to `error` (must fix), `warning` (should fix), or `info` (advisory).
4. **Package name** — follow the convention `skillsaw-<name>` on PyPI with module `skillsaw_<name>` (e.g. `skillsaw-acme-rules` / `skillsaw_acme_rules`).
5. **Tunable settings** — set anything a user could reasonably want to adjust
   (patterns, thresholds, allowlists) in `config_schema`; never hardcode it.

## Step 2: Create the package layout

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

Write `pyproject.toml` — the entry point is what makes it a plugin:

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

Set the entry point name (left of `=`) as the plugin's short name — it appears in
`skillsaw plugins` output and in `plugins: {disable: [...]}` config. Use it to point at the module that declares the rules.

Write `src/skillsaw_<name>/__init__.py`:

```python
from .rules import MyFirstRule

SKILLSAW_RULES = [MyFirstRule]
```

Declare every rule class the plugin provides in `SKILLSAW_RULES` — the explicit list skillsaw looks for.

## Step 3: Write the rules

Read [`references/rule-authoring.md`](references/rule-authoring.md) in this skill's directory for the full
rule template, the requirements every rule must meet (lint tree discovery,
line numbers, `config_schema`, `repo_types`, `default_enabled`, YAML and
markdown parsing rules), and the deterministic-autofix template with its
scoping and idempotency requirements. Follow it exactly — the requirements
match what skillsaw's own review process enforces.

Implement each rule as a subclass of `skillsaw.Rule` in
`src/skillsaw_<name>/rules.py`: use `context.lint_tree.find(NodeType)` to find
files, add violations via `self.violation(message, block=block, line=i)`, and
set tunable settings through `config_schema`.

### Add optional capabilities

Read [`references/extensions.md`](references/extensions.md) when the plugin needs any of:

- **A CLI subcommand** — add a `skillsaw-<name>` console script, dispatched as `skillsaw <name> [args...]` (registered plugins only).
- **A custom repo type** — declare a detector in `SKILLSAW_REPO_TYPES`; detected types scope rules (string entries in `repo_types`) and pull the type's `content_paths` into content linting.
- **Lint tree nodes** — use `SKILLSAW_TREE_CONTRIBUTORS` to attach plugin-defined
  blocks (`ContentBlock` for prose, `JsonConfigBlock` for machine config), and
  let rules read them with `lint_tree.find()`.

## Step 4: Write tests

<!-- skillsaw-disable-next-line content-unlinked-internal-reference -->
Write tests in `tests/test_rules.py` that cover at minimum:

1. Verify the rule fires on the fixture with the expected message and line number.
2. Check that clean content produces no violations.
3. Verify `config_schema` settings change behavior.
4. If the rule has autofix: check the fix removes only the flagged lines, re-checking
   fixed content finds nothing, and fixing twice is a no-op. Call
   `invalidate_read_caches()` (from `skillsaw.rules.builtin.utils`) — always call
   it before you re-check, since skillsaw caches file reads within a process.

Keep the fixture realistic — a CLAUDE.md that looks like a real project's,
not a one-line stub. Follow the example plugin's tests for the full pattern.

Run the tests:

```console
$ python -m venv .venv && .venv/bin/pip install -e . pytest
$ .venv/bin/pytest
```

## Step 5: Verify the plugin end-to-end

Install the package with `pip install -e .` in the same environment as skillsaw:

1. Run `skillsaw plugins` — the plugin appears with its rules and no ERROR lines.
2. Run `skillsaw lint <repo-with-violations>` — the rule fires, and the
   violation's `source` is `plugin:<name>` in `--format json` output; verify it.
3. Run `skillsaw explain <rule-id>` — it shows the rule's description and config.
4. If it has autofix: run `skillsaw fix --rule <rule-id>` to apply it; a second
   run changes nothing.
5. Run `skillsaw lint --no-plugins` — the rule disappears, confirming it loads
   via the entry point and never some other path.

## Step 6: Write the README

Write the plugin's README.md, documenting:

- Include what the rules enforce and why, with a violating and a passing example.
- Install instructions (`pip install skillsaw-<name>`).
- Include each rule's ID, default severity, and `config_schema` options with a `.skillsaw.yaml` snippet.
- Include how to disable: `plugins: {disable: [<name>]}` or per-rule `enabled: false`.

## Step 7: Build and publish to PyPI

Ask the user whether to publish now; if yes, run:

```console
$ pip install build twine
$ python -m build
$ twine upload dist/*
```

For a GitHub-hosted plugin, offer to set up [trusted
publishing](https://docs.pypi.org/trusted-publishers/) with a release
workflow instead of long-lived API tokens; always pin action SHAs.

After publishing, verify a fresh `pip install` from PyPI works in a clean environment:

```console
$ pip install skillsaw-<name>
$ skillsaw plugins
```

## Step 8: Wrap up

Report to the user:

- Package name, module, and entry point name
- Rules created (ID, severity, autofix support, config options)
- Test results
- Where it was published (or how to publish later)
- How users consume it: `pip install skillsaw-<name>` next to skillsaw, then
  rules run automatically; configure per rule ID in `.skillsaw.yaml`
