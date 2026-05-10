# Design: Repository Lint Tree

**Status:** Implementing
**Date:** 2026-05-10

## Overview

The lint tree is a tree data structure that represents everything lintable in a
repository. It is built once per lint run and serves as the single source of
truth for discovery. Rules walk the tree to find nodes they are compatible with.
The fix pipeline processes tree nodes. Everything is tree traversals.

## Motivation

Discovery was fragmented: content rules shared `gather_all_content_blocks()`,
structural rules each discovered files inside their own `check()`, and the fix
pipeline split into block-based and file-based paths. Format-specific logic
(CodeRabbit YAML, Cursor frontmatter) lived in free functions rather than being
encapsulated by the objects themselves.

## Tree Structure

```
LintTarget (base)
  ├── PluginNode             — plugin directory
  ├── SkillNode              — skill directory
  ├── ContentBlock (ABC)     — leaf with lintable text body
  │   ├── FileContentBlock          — plain files (CLAUDE.md, AGENTS.md, etc.)
  │   ├── FrontmatterContentBlock   — .mdc files
  │   └── CodeRabbitContentBlock    — instruction fragment from .coderabbit.yaml
```

### LintTarget

Base class for all tree nodes. Holds a `path` and a list of `children`.
Provides `walk()` for depth-first traversal and `find(type)` to collect all
descendants of a given type.

### ContentBlock

Abstract base class for leaf nodes with lintable text content. Defines:

- `read_body()` — lazily read content on first access
- `write_body()` — write fixed content back to the correct location
- `file_line()` — translate body-relative line numbers to file-absolute
- `__eq__` / `__hash__` — identity for matching across re-lint cycles

Each subclass encapsulates its format:

- **FileContentBlock**: reads/writes the whole file
- **FrontmatterContentBlock**: strips YAML frontmatter on read, preserves it on write
- **CodeRabbitContentBlock**: reads one instruction from `.coderabbit.yaml`, writes
  back via ruamel.yaml round-trip preserving comments and formatting

### PluginNode / SkillNode

Typed markers for structural nodes. Rules find them via `tree.find(PluginNode)`
and inspect their children or path to check structural requirements.

## Tree Builder

`build_lint_tree(context)` in `src/skillsaw/lint_tree.py` is the single
discovery entrypoint. It walks the repository once, creating typed nodes:

- Instruction files become FileContentBlock / FrontmatterContentBlock
- Plugin directories become PluginNode with content children
- Skill directories become SkillNode with content children
- `.coderabbit.yaml` instructions become CodeRabbitContentBlock children

The tree is cached on `RepositoryContext.lint_tree` (lazy property).
`rebuild_lint_tree()` invalidates the cache for use during fix loops.

## How Rules Use the Tree

Content rules walk the tree for ContentBlock leaves:

```python
for block in context.lint_tree.content_blocks():
    body = block.read_body()
    # analyze body...
```

Structural rules find specific node types:

```python
for plugin in context.lint_tree.find(PluginNode):
    if not (plugin.path / "plugin.json").exists():
        # report violation
```

## Fix Pipeline

Every violation references a tree node (ContentBlock). The fix pipeline has one
path: group violations by block, process each with block-scoped LLM tools
(read_block, write_block, replace_block_section, lint_block, diff_block).
No separate file-level fix path.

## CLI

`skillsaw tree` prints the discovered tree structure, showing all nodes with
their types and categories.
