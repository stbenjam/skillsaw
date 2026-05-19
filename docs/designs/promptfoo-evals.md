# Design: Promptfoo Eval Validation

**Status:** Implementing
**Date:** 2026-05-14

## Overview

Skillsaw gains the ability to lint promptfoo eval configurations — validating
YAML structure, enforcing assertion-type policies, and checking test metadata.
Promptfoo configs are discovered inside plugins/skills (under `evals/`
directories) and at the repo root for standalone promptfoo projects, integrated
into the lint tree as first-class nodes.

## Motivation

AI skills and plugins increasingly ship with promptfoo eval suites to verify
prompt quality, latency, cost, and output correctness. These eval configs are
YAML files with non-obvious structural requirements — easy to get wrong in ways
that silently produce broken or incomplete test runs. Linting them catches:

- Malformed YAML or wrong top-level types
- Missing `tests` / `scenarios` (config does nothing)
- Assertion entries without a `type` (silently skipped by promptfoo)
- File references (`file://`) pointing at nonexistent test files
- Policy violations: teams can mandate assertion types (e.g. every test must
  include a `cost` assertion) and cap thresholds (e.g. `latency` max 30s)

## Promptfoo Config Landscape

A survey of 17 real-world promptfoo repos informed the design:

- **`tests` entries can be strings**, not just dicts — `file://` refs and bare
  file paths are valid entries in a `tests` list
- **`description` on test entries is optional** — 4/17 repos omit it
- **`$ref` in assertions** is a template reference resolved at runtime by
  promptfoo — should not be flagged as "missing type"
- **`scenarios` can be a string** — a file reference, same as `tests`
- **Test fragment files** can be a YAML list of test-case dicts or a single dict
- **`defaultTest` assertions** apply to all tests — fragment tests inherit them

## Repository Type

A new `RepositoryType.PROMPTFOO` is added for standalone promptfoo projects.

Detection in `_detect_types()`:
- `promptfooconfig*.yaml` or `promptfooconfig*.yml` anywhere in the repo
  (recursive glob — the naming convention is unambiguous), OR
- `evals/` directory at root containing YAML files with at least one
  promptfoo-specific key (`providers`, `prompts`, `tests`, `scenarios`,
  `defaultTest`, `evaluateOptions`)

This type coexists with other types — a plugin repo can also be a promptfoo
repo.

## Lint Tree Integration

### `PromptfooConfigNode`

```python
@dataclass
class PromptfooConfigNode(LintTarget):
    is_fragment: bool = False  # True for test files referenced via file://
```

Tree placement depends on context:

```text
root
├── PluginNode (my-plugin/)
│   ├── CommandBlock (commands/foo.md)
│   ├── SkillNode (my-skill/)
│   │   ├── SkillBlock (SKILL.md)
│   │   └── PromptfooConfigNode (evals/smoke.yaml)
│   │       └── PromptfooConfigNode (evals/tests/cases.yaml, is_fragment=True)
│   └── HooksBlock (hooks/hooks.json)
└── PromptfooConfigNode (promptfooconfig.yaml)  ← standalone
```

- **Inside plugins/skills**: child of the PluginNode or SkillNode that owns
  the `evals/` directory
- **Standalone**: child of root
- **File ref fragments**: child of the PromptfooConfigNode that references them

### Tree Building

Discovery uses a two-pass approach in `build_lint_tree()`:

**Pass 1 — Discover confirmed promptfoo configs:**

- Inside each PluginNode/SkillNode: glob `evals/**/*.yaml`/`.yml`, parse with
  `read_yaml()`, only create a node if the file is a mapping with at least one
  promptfoo key. Add as child of the plugin/skill node.
- Anywhere in the repo: rglob `promptfooconfig*.yaml`/`.yml` — these are
  promptfoo by naming convention, no key check needed. Also glob root
  `evals/**/*.yaml`/`.yml` with key check. Add as children of root.
- Deduplicate via `seen` set, respect `_is_excluded()`.

**Pass 2 — Resolve file refs from confirmed configs:**

- For each confirmed config node, parse and extract `file://` string
  references from `tests` (both `tests: "file://..."` and string entries in
  tests lists).
- Resolve paths relative to the config file's directory (per promptfoo spec).
- Skip glob patterns (`*`, `?`), non-YAML extensions (`.csv`, `.xlsx`, `.js`,
  `.ts`, `.py`, `.jsonl`), and remote URLs.
- Add referenced files as children of the config node with
  `is_fragment=True`.
- If the file is already in `seen` (shared fragment), skip — first config
  owns it in the tree.

### Helpers

These live in `src/skillsaw/rules/builtin/promptfoo.py` alongside the rules:

```python
_PROMPTFOO_KEYS = {"providers", "prompts", "tests", "scenarios",
                   "defaultTest", "evaluateOptions"}

def _is_promptfoo_config(data: object) -> bool:
    """True if data is a mapping with at least one promptfoo-specific key."""

def _resolve_file_ref(ref: str, config_dir: Path) -> Optional[Path]:
    """Resolve a file:// ref relative to config dir.
    Returns None for globs, non-YAML, remote URLs."""

def _extract_file_refs(data: dict) -> List[str]:
    """Extract string file references from a parsed config's tests field."""
```

## Rules

### `promptfoo-valid` (error)

Structural validation of promptfoo YAML. Discovers nodes via
`context.lint_tree.find(PromptfooConfigNode)`.

**For full configs** (`is_fragment=False`):

- Top-level must be a mapping
- Warn if neither `tests` nor `scenarios` is present
- Validate `scenarios` type (list or string)
- For `tests`: accept both dict entries and string entries
  - Dict entries: validate `assert` is an array if present, each assertion is a
    dict with a `type` key (skip entries with `$ref`)
  - String entries: resolve as file reference, error if the file doesn't exist
- No warning for missing `description` (it is optional per promptfoo spec)

**For test fragments** (`is_fragment=True`):

- Top-level can be a list of test-case dicts or a single dict
- Each test entry validated same as inline: dict shape, assert arrays, assert
  entry dicts with `type` (skipping `$ref`)

### `promptfoo-assertions` (warning, `enabled: false`)

Policy rule — enforces that tests include specific assertion types and that
thresholds stay within bounds. Configurable via:

```yaml
rules:
  promptfoo-assertions:
    required-types: [cost, latency]
    threshold-constraints:
      cost:
        max: 2.0
      latency:
        max: 30000
```

For each full config node:

- Collect `defaultTest` assertion types
- Collect all test dicts: inline test entries + tests from fragment children
  (via `_collect_tests()`)
- For each test: union its assertion types with `defaultTest` types, report
  any missing required types
- Check threshold values against configured min/max bounds

### `promptfoo-metadata` (warning, `enabled: false`)

Policy rule — enforces that test entries include specific metadata keys.
Configurable via:

```yaml
rules:
  promptfoo-metadata:
    required-keys: [owner, category]
```

For each full config node, collects all test dicts (inline + fragments) and
checks that each test's `metadata` mapping contains the required keys.

### Common: `repo_types`

All three rules set `repo_types` to include every type where promptfoo configs
can appear:

```python
{RepositoryType.SINGLE_PLUGIN, RepositoryType.MARKETPLACE,
 RepositoryType.AGENTSKILLS, RepositoryType.DOT_CLAUDE,
 RepositoryType.PROMPTFOO}
```

## Files

| File | Change |
|------|--------|
| `src/skillsaw/context.py` | Add `PROMPTFOO` to `RepositoryType`, detection in `_detect_types()` |
| `src/skillsaw/lint_target.py` | Add `PromptfooConfigNode(LintTarget)` with `is_fragment` and `tree_label()` |
| `src/skillsaw/lint_tree.py` | Two-pass promptfoo node builder: discover configs, resolve file refs |
| `src/skillsaw/rules/builtin/promptfoo.py` | Three rules + helpers (`_is_promptfoo_config`, `_resolve_file_ref`, `_extract_file_refs`) |
| `src/skillsaw/config.py` | Add `RepositoryType.PROMPTFOO` references |

## Test Plan

### Unit tests (`tests/test_promptfoo_rules.py`)

- String entries in `tests` lists — no false positive, file existence checked
- `$ref` in assertions — no false positive
- No `description` on tests — no warning
- File ref resolution: existing file creates fragment node, gets validated
- File ref to missing file — error from `promptfoo-valid`
- Fragment validation: list of dicts, single dict
- Assertions/metadata checks applied through file ref boundary with `defaultTest`
- Glob/non-YAML refs — skipped gracefully
- `PromptfooConfigNode` discovery via lint tree (child of plugin/skill node)
- `RepositoryType.PROMPTFOO` detection
- Non-promptfoo YAML in `evals/` — not misidentified (no promptfoo keys)
- Shared fragment deduplication

### Integration tests (`tests/test_integration.py`)

- Fixture for standalone promptfoo repo type detection
- Verify promptfoo rules fire for skill repos with `evals/`

### Fixtures (`tests/fixtures/`)

- Standalone promptfoo repo with `promptfooconfig.yaml`
- Skill with `evals/` containing configs + referenced test fragment files
- Non-promptfoo YAML in `evals/` (should be ignored)
- Config with `file://` refs to existing and missing files

## Verification

1. `make test` — all pass
2. `make lint` — clean
3. Version bump + `make update`
4. Test against `openshift-eng/ai-helpers` — exit 0
