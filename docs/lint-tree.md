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
