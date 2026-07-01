# Plugin extension points reference

Optional capabilities beyond rules. Read this when the plugin needs a CLI,
a custom repository type, or its own lint tree nodes. Full documentation:
https://skillsaw.org/plugins/

## CLI subcommand

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

## Custom repository types

When the plugin supports a repository layout skillsaw doesn't know (a new
assistant's config format), declare it on the plugin module:

```python
from skillsaw.plugins import PluginRepoType

SKILLSAW_REPO_TYPES = [
    PluginRepoType(
        name="acme",
        description="Repository configured for the ACME assistant",
        detect=lambda root: (root / "ACME.md").exists() or (root / ".acme").is_dir(),
        content_paths=["ACME.md", ".acme/rules/*.md"],
    ),
]
```

When `detect(root_path)` returns True for the linted repository:

- The type name appears in the lint report's detected repository types.
- Rules scope to it by listing the name as a **string** in `repo_types`
  (mixing freely with builtin `RepositoryType` members):

  ```python
  class AcmeConfigRule(Rule):
      repo_types = {"acme"}
  ```

- The type's `content_paths` globs are pulled into content linting: matched
  files become content blocks and every `content-*` rule covers them
  automatically.

Names must be kebab-case and unique — collisions with builtin type values or
other plugins are skipped with a warning. A crashing detector becomes a
`plugin-load-error` violation; the lint continues.

## Lint tree contributors

For files that need *dedicated* rules (rather than the generic content
rules), contribute nodes to the lint tree:

```python
from dataclasses import dataclass

from skillsaw.blocks import JsonConfigBlock


@dataclass(eq=False)
class AcmeConfigBlock(JsonConfigBlock):
    """.acme/config.json — machine config, never linted as prose."""

    category: str = "acme-config"


def contribute_acme_config(context, root):
    config_path = context.root_path / ".acme" / "config.json"
    if config_path.exists():
        return [AcmeConfigBlock(path=config_path)]
    return []


SKILLSAW_TREE_CONTRIBUTORS = [contribute_acme_config]
```

Each contributor is invoked as `contribute(context, root)` during tree
construction and returns an iterable of node instances (or None). The
plugin's rules then discover them with `context.lint_tree.find(AcmeConfigBlock)`.

Contract:

- **Choose the right base class**: prose for an agent's context window
  subclasses `ContentBlock`/`FileContentBlock` (content-quality rules apply
  automatically); structured machine config subclasses `JsonConfigBlock` so
  content rules never lint JSON as instruction text.
- skillsaw drops contributed nodes that duplicate files already in the tree
  and applies the user's `exclude` patterns.
- A contributor that raises (or returns non-node values) produces a
  `plugin-load-error` violation; tree construction and the lint continue.
