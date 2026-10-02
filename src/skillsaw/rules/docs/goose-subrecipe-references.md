Checks literal local `sub_recipes[].path` references in Goose recipes. This
rule is opt-in and reports warnings by default. Enable it with
`--rule goose-subrecipe-references` or:

```yaml
rules:
  goose-subrecipe-references:
    enabled: true
```

## Path resolution

Goose v1.52.0 resolves a literal `.yaml` or `.json` file path from the working
directory. Skillsaw uses the workspace owning `.goose/recipes/`, or the lint
directory for `--type goose`. A leading `{{ recipe_dir }}/` (also accepted
without spaces) resolves from the recipe's own directory.

Only targets contained in the lint root are checked or read. References to
personal or absolute paths, remote sources, library names without extensions,
and other templates are skipped because they require runtime configuration.
Existing contained subrecipes are linted even when this reference rule is off.

## How to fix

Correct missing file paths or commit the referenced recipe. If another build
step creates the files, use per-rule exclusions or disable the rule. Multiple
missing paths produce one finding per recipe. The diagnostic names the affected
fields without echoing potentially sensitive path values.
