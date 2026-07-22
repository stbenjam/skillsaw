# CodeRabbit (`.coderabbit.yaml`)

<!-- Repo-root-relative src/... and cross-reference paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

## Upstream source(s)
- Configuration reference (authoritative, auto-generated from the schema):
  https://docs.coderabbit.ai/reference/configuration
- Published JSON Schema: https://coderabbit.ai/integrations/schema.v2.json
  (referenced in-file via a `yaml-language-server` `$schema` directive)
- Guide: https://docs.coderabbit.ai/configure-coderabbit/

## What to check
- New/renamed top-level config keys (`reviews`, `chat`, `language`, tool integrations).
- Changes to the `instructions` fields that are fed to the LLM.
- Re-verify skillsaw's hand-copied schema snapshot against the live
  `schema.v2.json`: the `KNOWN_TOP_LEVEL_KEYS` tuple and the
  `VALID_REVIEW_PROFILES` enum in `src/skillsaw/rules/builtin/coderabbit/schema_valid.py`.
  If upstream adds a top-level key or a new `reviews.profile` value, update the
  snapshot so `coderabbit-schema-valid` keeps pace.
- Whether skillsaw should validate more of the schema (it currently checks
  well-formedness plus near-miss top-level keys and the `reviews.profile` enum).

## skillsaw rules that map
- `coderabbit-yaml-valid` — `src/skillsaw/rules/builtin/coderabbit/yaml_valid.py`
- `coderabbit-schema-valid` — `src/skillsaw/rules/builtin/coderabbit/schema_valid.py`

## Sync notes
- `coderabbit-yaml-valid` validates that `.coderabbit.yaml` is parseable YAML.
- `coderabbit-schema-valid` adds lightweight schema-conformance checks (near-miss
  unknown top-level keys, invalid `reviews.profile` enum) from a hand-copied
  snapshot of `schema.v2.json`. Re-verify that snapshot on each maintenance pass
  (see "What to check"). If upstream adds strict/required structure worth
  enforcing, extend this rule or add a new one (default `enabled: auto`/`false`).
