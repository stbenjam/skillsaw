# Scaffolding

`skillsaw add` scaffolds marketplaces, plugins, and components with best-practice structure, CI, and branding out of the box.

## Initialize a Marketplace

```bash
# Interactive (prompts for name, owner, colors)
skillsaw add marketplace

# Non-interactive
skillsaw add marketplace --name my-plugins --owner myuser --color-scheme ocean-blue
```

This creates the full marketplace structure: `marketplace.json`, `settings.json`, GitHub Pages site, GitHub Actions CI, Makefile, and an example plugin.

## Add Components

```bash
# Add a plugin to a marketplace
skillsaw add plugin my-plugin

# Add a skill, command, agent, or hook
skillsaw add skill my-skill
skillsaw add command greet
skillsaw add agent helper
skillsaw add hook PreToolUse
```

## Context Detection

skillsaw automatically detects your repo type and places files in the right location:

- **Marketplace** — components go under `plugins/<name>/`
- **Single-plugin repo** — components go in the repo root
- **`.claude/` repo** — components go under `.claude/`

In a marketplace with multiple plugins, specify `--plugin <name>` or skillsaw will prompt interactively.
