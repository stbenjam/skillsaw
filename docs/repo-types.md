# Repository Types

skillsaw automatically detects your repository structure. A repository can match multiple types simultaneously (e.g. an agentskills repo that also has `.coderabbit.yaml`).

## agentskills.io Skills

Standalone skill repositories following the [agentskills.io](https://agentskills.io) specification:

```
my-skill/
├── SKILL.md              # Required: metadata + instructions
├── scripts/              # Optional: executable code
├── references/           # Optional: documentation
├── assets/               # Optional: templates, resources
├── evals/                # Optional: evaluation tests
│   └── evals.json
└── <any-dir>/            # Arbitrary directories allowed per spec
```

Skill collections (multiple skills in subdirectories) are also supported:

```
skills-repo/
├── skill-one/
│   └── SKILL.md
└── skill-two/
    └── SKILL.md
```

Standard discovery paths (`.claude/skills/`, `.github/skills/`, `.agents/skills/`) are checked automatically.

## Single Plugin

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json
├── commands/
│   └── my-command.md
├── skills/
│   └── my-skill/
│       └── SKILL.md
└── README.md
```

## Marketplace (Multiple Plugins)

skillsaw supports multiple marketplace structures per the [Claude Code specification](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces):

### Traditional Structure (plugins/ directory)

```
marketplace/
├── .claude-plugin/
│   └── marketplace.json
└── plugins/
    ├── plugin-one/
    │   ├── .claude-plugin/
    │   └── commands/
    └── plugin-two/
        ├── .claude-plugin/
        └── commands/
```

### Flat Structure (root-level plugin)

```
marketplace/
├── .claude-plugin/
│   └── marketplace.json    # source: "./"
├── commands/
│   └── my-command.md
└── skills/
    └── my-skill/
```

### Custom Paths and Mixed Structures

Plugins from `plugins/`, custom paths, and remote sources can coexist in one marketplace. Only local sources are validated.

## `.claude/` Directory

Repositories with a `.claude/` directory containing commands, skills, hooks, agents, or rules. When APM is present, `.claude/` is treated as compiled output and this type is not detected.

## CodeRabbit

Repositories with a `.coderabbit.yaml` file. skillsaw validates the instruction fragments within the config.

## Promptfoo

Repositories with promptfoo eval configs (`promptfooconfig*.yaml` or YAML files in `evals/` directories). Prompt strings in the config are treated as content blocks, so all `content-*` rules apply to them automatically. Dedicated `promptfoo-*` rules validate config structure, assertion coverage, and metadata.

## APM (Agent Package Manager)

Repositories with an `.apm/` directory or `apm.yml` file. APM manages dependencies and compiles instruction files for all supported agents (`.claude/`, `.cursor/rules/`, `.github/instructions/`, etc.). When APM is present it is the authoritative source — `.claude/` is treated as compiled output.
