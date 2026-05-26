# Configuration

Generate a default `.skillsaw.yaml` in your repository root:

```bash
skillsaw init
```

This creates a config file with all builtin rules, their defaults, and
descriptions. Edit it to enable, disable, or customize rules for your project.

## Example Configuration

```yaml
version: "0.10.1"

rules:
  content-weak-language:
    enabled: auto
    severity: warning

  content-critical-position:
    enabled: auto
    severity: warning
    min-lines: 50

  mcp-prohibited:
    enabled: false
    allowlist: []

exclude:
  - "vendor/**"
  - "generated/**"

content-paths:
  - "docs/runbooks/*.md"

strict: false
```

## Version Pinning

The config file includes a `version` field set to the skillsaw version that
created it. New rules introduced after that version are automatically skipped
unless you bump the version or explicitly enable them. Repos **without** a
`.skillsaw.yaml` run all rules at the latest version — you get new rules
automatically but may occasionally fail after a skillsaw upgrade.

## Exclude Patterns

Skip files and directories using glob patterns:

```yaml
exclude:
  - "vendor/**"
  - "generated/**"
  - "node_modules/**"
```

By default, skillsaw excludes `**/template/**`, `**/templates/**`, and
`**/_template/**` directories. These defaults are replaced when you specify
your own `exclude` list.

Exclude patterns apply to **all** rules, including custom rules loaded via
`custom-rules`. Any violation whose file path matches an exclude pattern is
filtered out before results are reported.

## Per-Rule Excludes

Exclude specific files from a single rule using the `exclude` key in the
rule's config:

```yaml
rules:
  content-weak-language:
    enabled: true
    exclude:
      - "docs/legacy/**"
      - "CHANGELOG.md"
```

This is useful when a rule produces false positives on specific files but
you still want it enabled globally. Per-rule excludes use the same glob
syntax as global `exclude` patterns.

## Inline Suppression

Suppress specific rules on specific lines using comment directives directly
in your files. Both HTML comments (for markdown) and hash comments (for YAML)
are supported.

### Markdown (HTML comments)

```markdown
<!-- skillsaw-disable content-weak-language -->
This section intentionally uses informal language.
<!-- skillsaw-enable content-weak-language -->
```

Suppress a single line:

```markdown
<!-- skillsaw-disable-next-line content-tautological -->
Follow best practices for error handling.
```

Suppress multiple rules at once:

```markdown
<!-- skillsaw-disable content-weak-language, content-tautological -->
```

Re-enable all suppressed rules:

```markdown
<!-- skillsaw-enable -->
```

Multi-line HTML comments are also supported:

```markdown
<!--
    skillsaw-disable content-weak-language
-->
```

### YAML (hash comments)

For YAML files (`.coderabbit.yaml`, `promptfooconfig.yaml`, etc.), use `#` comments:

```yaml
# skillsaw-disable promptfoo-valid
prompts:
  - "{{prompt}}"
# skillsaw-enable promptfoo-valid
```

```yaml
# skillsaw-disable-next-line coderabbit-yaml-valid
instructions: missing-value
```

Only full-line `#` comments are recognized — inline comments like
`key: value # skillsaw-disable` are ignored.

!!! note
    Inline suppression only affects rules that are already enabled. It cannot
    be used to enable a normally disabled rule.

## Content Paths

By default, content intelligence rules only analyze recognized instruction
files (CLAUDE.md, AGENTS.md, `.cursor/rules/`, `.apm/instructions/`, etc.).
Use `content-paths` to extend coverage to any text files that contain
instructions for humans or AI agents — markdown, `.mdc`, `.txt`, or any
other format:

```yaml
content-paths:
  - "src/**/instructions/**/*.md"
  - ".cursor/rules/*.mdc"
  - "docs/runbooks/*.txt"
```

Matched files are analyzed by all `content-*` rules and support LLM-powered
fixes via `skillsaw fix --llm`.
