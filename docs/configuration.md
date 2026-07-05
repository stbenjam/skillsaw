# Configuration

Generate a default `.skillsaw.yaml` in your repository root:

```bash
skillsaw init
```

This creates a config file with all builtin rules, their defaults, and
descriptions. Edit it to enable, disable, or customize rules for your project.

## Config File Discovery

skillsaw looks for a config file starting in the linted directory and walking
**up** the directory tree, all the way to the filesystem root. In each
directory it checks, in order:

1. `.skillsaw.yaml`
2. `.skillsaw.yml`
3. `.claudelint.yaml` (legacy name, still supported)
4. `.claudelint.yml`

The first match wins. Use `--config PATH` to point at a specific file and
skip discovery entirely. If no config is found, all rules run with their
defaults at the latest version.

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
fail-on: error
```

## Version Pinning

The config file includes a `version` field set to the skillsaw version that
created it. New rules introduced after that version are automatically skipped
unless you bump the version or explicitly enable them. Repos **without** a
`.skillsaw.yaml` run all rules at the latest version — you get new rules
automatically but may occasionally fail after a skillsaw upgrade.

!!! warning "Always set `version`"
    A config file **without** a `version` field is treated as version
    `0.6.0`. Every rule introduced after 0.6.0 is then silently skipped —
    which is most of them. skillsaw prints a warning when it loads such a
    config, but the lint still passes, so it is easy to miss. Always set
    `version` to your skillsaw version (`skillsaw --version`) and bump it
    when you upgrade.

## Enabling Rules

Each rule's `enabled` key accepts three values:

| Value | Meaning |
|-------|---------|
| `true` | Always run the rule, unconditionally |
| `false` | Never run the rule |
| `auto` | Run the rule where it applies: when the rule declares repository types or file formats, only where those are detected (e.g. plugin rules only run in plugin repos); rules with no such gating run everywhere |

`auto` also respects the config `version` gate: a rule newer than the
pinned `version` stays off until you bump it. `enabled: true` bypasses
that gate and turns the rule on unconditionally — so prefer `auto` unless
you deliberately want a rule regardless of version or repo detection.

Most rules default to `auto`, so they activate only where they make sense.
`skillsaw explain <rule-id>` shows whether a rule is active in your
repository and why.

Each rule also has a `severity`, one of `error`, `warning`, or `info`.
By default only errors fail the lint; warnings fail it in
[strict mode](#strict-mode), and the [`fail-on`](#failure-threshold)
threshold can make any severity — including info — fail the run.
Info-level violations are shown with `--verbose` (and always when
`fail-on: info` makes them fatal).

```yaml
rules:
  content-weak-language:
    enabled: auto
    severity: warning
```

## Strict Mode

With `strict: true`, warnings fail the lint just like errors:

```yaml
strict: true
```

The `--strict` CLI flag does the same for a single run. Note that the CLI
flag can only *upgrade* to strict — there is no `--no-strict` flag, so a
`strict: true` in the config file cannot be overridden from the command
line.

## Failure Threshold

`fail-on` generalizes strict mode: violations at the given severity or
above make the run exit non-zero.

```yaml
fail-on: info   # any violation at info or above fails the run
```

| `fail-on` | Fails the run |
|-----------|---------------|
| `error` (default) | errors only |
| `warning` | errors and warnings (same as `strict: true`) |
| `info` | any violation |

`strict: true` is shorthand for `fail-on: warning`. When both are set, the
strictest one wins — neither option can loosen the other, so adding
`fail-on: info` to a config that already has `strict: true` just tightens
the threshold.

The `--fail-on` CLI flag does the same for a single run and, like
`--strict`, can only tighten the config file's setting.

`fail-on: info` is useful for ratcheting: once a repo is at zero
violations, it stays that way — new info-level findings (including from
rules added in newer skillsaw versions) fail CI instead of accumulating
silently. When info violations are what failed the run, the text output
shows them even without `--verbose`. Pair it with a
[baseline](baseline.md) to adopt the threshold before reaching zero.

## Custom Rules

Load project-specific rules from Python files with the `custom-rules` key.
Relative paths resolve against the config file's directory:

```yaml
custom-rules:
  - lint/no_placeholder_urls.py
  - lint/require_owner_section.py
```

Each file defines one or more `Rule` subclasses that run alongside the
builtin rules and are configured in the same `rules:` section by rule ID.
See the [Custom Rules guide](custom-rules.md) for how to write them, and
[Rule Plugins](plugins.md) for sharing rules across repositories as
pip-installable packages.

## Exclude Patterns

Skip files and directories using glob patterns:

```yaml
exclude:
  - "vendor/**"
  - "generated/**"
  - "node_modules/**"
```

Patterns match against the file path relative to the lint root using
Python `fnmatch` syntax, where `*` also crosses `/`. A leading `**/`
additionally matches at the root of the repository, so `**/templates/**`
excludes both a top-level `templates/` directory and any nested
`a/templates/`.

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

Matched files are analyzed by all `content-*` rules.

## Rule Plugins

Rules from installed [rule plugins](plugins.md) run automatically. The
`plugins` key controls which plugins load:

```yaml
plugins:
  enabled: true          # default; set false to skip all rule plugins
  disable: [acme-rules]  # skip specific plugins by name (see `skillsaw plugins`)
```

`plugins: false` is accepted as a shorthand for `enabled: false`. The
`--no-plugins` CLI flag skips all plugins for a single run. Individual
plugin *rules* are configured in the normal `rules:` section by rule ID,
exactly like builtin rules.
