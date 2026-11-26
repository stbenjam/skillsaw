# Lint Tree

`skillsaw tree` visualizes the typed lint tree — the internal data structure that all rules operate on. Every lintable entity (plugins, skills, commands, agents, instruction files, config files) is a typed node in the tree.

## Usage

```bash
# View the lint tree
skillsaw tree

# View a specific path
skillsaw tree /path/to/repo

# Output as Graphviz DOT format
skillsaw tree --format dot
```

## Example Output

```
my-marketplace/
    ├── AGENTS.md (agents-md)
    ├── marketplace.json
    ├── plugins/ [marketplace]
    │   └── my-plugin/ [plugin]
    │       ├── hello.md (command)
    │       └── my-skill/ [skill]
    │           └── SKILL.md (skill)
    └── .coderabbit.yaml
        └── reviews.instructions (coderabbit)
```

## How Rules Use It

Rules discover nodes via typed queries on the tree:

```python
# Find all plugin nodes
for plugin in context.lint_tree.find(PluginNode):
    ...

# Find all skill blocks
for skill in context.lint_tree.find(SkillBlock):
    ...
```

This ensures rules only operate on the correct file types and supports multi-type repositories (e.g., a marketplace that also has CodeRabbit config).

## Codex instruction selection

Discovered `AGENTS.override.md` files receive content checks without extra
configuration, including files in `.apm/`. If an override or selected fallback
already serves as a command, agent, or skill, it keeps that role. A child node
labeled `Codex instruction file validation` adds the empty-file and UTF-8
checks without duplicating its prose.

Use `skillsaw tree /path/to/repo --codex-instructions --cwd services/payments`
to inspect Codex's root-to-cwd selection and cumulative byte budget. Add
`--format json` for per-file sizes, statuses, setting sources and assumptions.
The supplied path is the project root; skillsaw does not read global Codex
configuration. See [Codex project instructions](rules/codex-project-instructions.md)
for explicit configuration, the opt-in CI rule, and released loader semantics.
