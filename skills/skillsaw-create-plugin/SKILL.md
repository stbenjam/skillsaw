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
dependencies = ["skillsaw>=0.14"]

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

Each rule subclasses `skillsaw.Rule` in `src/skillsaw_<name>/rules.py`:

```python
from typing import List

from skillsaw import RepositoryContext, Rule, RuleViolation, Severity
from skillsaw.blocks import InstructionBlock


class MyFirstRule(Rule):
    """One-line summary of what this enforces."""

    config_schema = {
        "patterns": {
            "type": "list",
            "default": ["TODO"],
            "description": "Patterns to flag",
        },
    }

    @property
    def rule_id(self) -> str:
        return "my-rule-id"

    @property
    def description(self) -> str:
        return "Instruction files should not contain TODO markers"

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
                        self.violation(f"Found marker: {line.strip()}", block=block, line=i)
                    )
        return violations
```

Rules you must follow when writing rules:

- **Discover files through the lint tree** (`context.lint_tree.find(NodeType)`),
  never by walking the filesystem. Common block types from `skillsaw.blocks`:
  `InstructionBlock` (CLAUDE.md, AGENTS.md, …), `SkillBlock`, `CommandBlock`,
  `AgentBlock`, `ClaudeMdBlock`. Run `skillsaw tree` on a target repo to see
  its nodes.
- **Report a line number** on every violation traceable to a line; never
  fabricate one when it is not.
- **Pass `block=`** to `self.violation()` for content violations — line
  numbers then map to the right file lines even for YAML-embedded bodies.
- **Expose tunable settings through `config_schema`** and read them from
  `self.config`. Users configure the rule in `.skillsaw.yaml` under `rules:`
  by its rule ID, exactly like builtin rules.
- **Declare `repo_types`** when the rule only applies to certain repository
  types — the rule then activates only on matching repositories.
- Parse YAML with `read_yaml_commented()` from `skillsaw.utils` (preserves
  line numbers), never `yaml.safe_load()`.
- Read markdown structure (links, fences, headings) from `block.markdown`
  accessors, never hand-rolled regexes.

### Optional: deterministic autofix

To make violations fixable by `skillsaw fix`, set `autofix_confidence` and
override `fix()`:

```python
from skillsaw import AutofixConfidence, AutofixResult


class MyFirstRule(Rule):
    autofix_confidence = AutofixConfidence.SAFE  # or SUGGEST

    def fix(self, context, violations) -> List[AutofixResult]:
        by_file = {}
        for v in violations:
            by_file.setdefault(v.file_path, []).append(v)

        results = []
        for path, file_violations in by_file.items():
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
            remove = {v.file_line for v in file_violations if v.file_line}
            fixed = "".join(ln for i, ln in enumerate(lines, start=1) if i not in remove)
            if fixed != original:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Removed marker lines",
                        violations_fixed=file_violations,
                    )
                )
        return results
```

Autofix rules:

- Fixes must be **deterministic and scoped to the violation's exact location**
  (use `v.file_line`; never `str.replace()` across the whole file — it can
  match the wrong occurrence).
- Use `AutofixConfidence.SAFE` only when the fix cannot change meaning;
  otherwise use `SUGGEST` (applied only with `skillsaw fix --suggest`).
- Fixes must be idempotent: fixing already-fixed content produces no changes.
- Do not build fixes on LLM hooks — plugins provide deterministic fixes only.

### Optional: ship a CLI subcommand

If the plugin needs its own commands (for example an `accept` command that
appends currently-flagged values to the rule's config), add a console script
named `skillsaw-<name>` to `pyproject.toml`:

```toml
[project.scripts]
skillsaw-<name> = "skillsaw_<name>.cli:main"
```

skillsaw dispatches `skillsaw <name> [args...]` to that executable
(registered plugins only), forwarding arguments and the exit code. The
script owns its own argument parsing and can `import skillsaw` to reuse the
config loader and lint tree.

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
