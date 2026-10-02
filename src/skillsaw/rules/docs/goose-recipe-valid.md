Checks the static authoring fields of Goose recipes against the
[v1.52.0 loader and validator](https://github.com/aaif-goose/goose/tree/v1.52.0/crates/goose/src/recipe).
This rule is opt-in. Enable it with `--rule goose-recipe-valid` or:

```yaml
rules:
  goose-recipe-valid:
    enabled: true
```

## What it checks

- A mapping with `title`, `description`, and nonempty `instructions` or `prompt`.
- String metadata and activity arrays; omitted `version` defaults to `1.0.0`.
- Parameter metadata, input/requirement enums, defaults for optional parameters,
  and the prohibition on file parameter defaults.
- Extension types, names, `cmd`/`args` for stdio, `uri` for streamable HTTP,
  and string arrays/maps for their common declarations.
- Subrecipe names/paths and the shape of values, settings, author, response and retry.

Nested `recipe:` documents, numeric/boolean YAML string scalars, optional nulls,
unknown fields and extension descriptions omitted by the author are accepted.
Findings are consolidated per recipe and respect configured severity.

## How to fix

Correct the fields named in the finding, then run `goose recipe validate` to
check template and runtime constraints. For generated recipes or conventions
outside this static contract, configure per-rule exclusions or disable the rule.

## Discovery and limits

Automatic discovery reads `.goose/recipes/` in each workspace. `--type goose`
also selects top-level `.yaml`, `.yml` and `.json` files in the lint directory.
Known project configuration filenames are skipped in this explicit mode.
Local subrecipe paths inside the lint root are followed. See
[repository types](../repo-types.md#goose-recipes).

Only extracted `instructions`, `prompt` and `activities` go through prose rules.
External extensions go through the shared MCP credential and policy rules even
when this format rule is disabled. Prose fixes are disabled because decoded
strings do not carry safe write spans for every YAML scalar style or JSON escape.

This is a focused static check. Template syntax, parameter usage, detailed model
settings, retry execution and response-schema compilation remain with
`goose recipe validate`. Skillsaw never renders templates, executes commands or
fetches dependencies. Use rule exclusions for generated recipes or disable
checks that do not fit your authoring workflow.
