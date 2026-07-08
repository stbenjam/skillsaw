# CodeRabbit (`.coderabbit.yaml`)

## Upstream source(s)
- Configuration reference (authoritative, auto-generated from the schema):
  https://docs.coderabbit.ai/reference/configuration
- Published JSON Schema: https://coderabbit.ai/integrations/schema.v2.json
  (referenced in-file via a `yaml-language-server` `$schema` directive)
- Guide: https://docs.coderabbit.ai/configure-coderabbit/

## What to check
- New/renamed top-level config keys (`reviews`, `chat`, `language`, tool integrations).
- Changes to the `instructions` fields that are fed to the LLM.
- Whether skillsaw should validate more than well-formedness (currently it only checks
  that the file is valid YAML).

## skillsaw rules that map
- `coderabbit-yaml-valid` — `src/skillsaw/rules/builtin/coderabbit/yaml_valid.py`

## Sync notes
- The rule only validates that `.coderabbit.yaml` is parseable YAML; it does not validate
  against the CodeRabbit schema. If upstream adds strict/required structure worth
  enforcing, that would be a new rule (default `enabled: auto`/`false`).
