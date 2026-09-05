# Upgrading to 0.20.0

Skillsaw 0.20.0 expands host-specific validation and improves discovery, autofix
consistency and adoption workflows. Review these changes when updating an existing
repository from 0.19.0.

## Choose when to enable new rules

The `version` in `.skillsaw.yaml` gates new rules whose activation is `auto`.
Keeping `version: "0.19.0"` postpones those rules while you upgrade the executable;
changing it to `"0.20.0"` lets applicable new rules run. An explicit
`enabled: true` bypasses the version gate. Run `skillsaw lint -v` and use
`skillsaw explain <rule-id>` to review the effective configuration.

See [configuration](configuration.md#enabling-rules) for activation and severity
settings. Existing rules can also receive compatibility fixes regardless of the
version gate.

## Update hook rule overrides

`hooks-json-valid` is now [`claude-hooks-valid`](rules/claude-hooks-valid.md).
The old name remains an alias for Claude validation in configuration, CLI flags,
suppressions and baselines. Other hosts have their own shape rules, including
`codex-hooks-valid`, `grok-hooks-valid` and `muse-hooks-valid`.

An old `hooks-json-valid: {enabled: false}` entry therefore disables only the
Claude rule. Configure each host's rule directly when needed. Some Codex findings
have new wording and IDs, so old baseline entries may no longer match; review the
findings before accepting them again. Shared hook command checks continue to apply
across host formats.

## Review findings and baseline policy

Host validators now accept more configurations their released loaders support and
report additional malformed fields those loaders discard. Several errors are
consolidated by their actual failure scope. Explicit severity settings now also
reach primary Grok config and Antigravity MCP findings whose default classification
is WARNING; independently classified secondary advisories keep their documented
severity.

The `function/method` group in
[`content-inconsistent-terminology`](rules/content-inconsistent-terminology.md) is
now opt-in, because these terms commonly describe different things. Other groups
retain their defaults.

`skillsaw baseline` includes INFO findings automatically when the configuration
sets `fail-on: info`. If only the lint command uses `--fail-on info`, create the
baseline with `skillsaw baseline --include-info`. Review and fix new findings
before deliberately accepting existing ones. See the [baseline guide](baseline.md).

## Keep installed content under its owner's control

Externally sourced skills remain visible to diagnostics by default, but autofix
leaves them unchanged. Linked worktrees and nested local lock sources now use the
same ownership decisions for discovery and fixing. Plugins under `.codex/plugins/`
also remain diagnostic-only. See
[external-content policy](configuration.md#external-content).

SAFE fixes remain the default. Suggested rewrites require `skillsaw fix --suggest`;
ambiguous MCP tool names and generated instruction-file banners have additional
guards to preserve intended content.

## Check CI and deprecated commands

The GitHub Action now honors an explicit `with.version` package version. Leaving
that input empty uses the source at the selected action ref. Keep the action ref
and package version intentional; see [CI integration](ci.md).

`skillsaw docs` and [`skillsaw add`](scaffolding.md) are deprecated but remain
available during the transition. [Deprecated rules](rules/deprecated.md) no longer
run under `auto`; explicitly enabling one retains it temporarily and emits a
deprecation notice. Existing
published rule explanations and the site replace the generated rule-reference
workflow described in [CI integration](ci.md#committed-generated-docs).
