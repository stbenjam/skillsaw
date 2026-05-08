# Add `--format` and `--output` flags with text/json/sarif/html formatters

## Context

skillsaw currently only outputs human-readable text. There's no way to verify that
the linter actually scanned anything — a bug that scans zero files exits 0 with
"All checks passed!" Adding structured output formats solves this (stats derivable
from every format) and also enables GitHub Code Scanning (SARIF) and shareable
reports (HTML).

## CLI interface

- `--format FORMAT` — what goes to **stdout** (default: `text`). One of: `text`, `json`, `sarif`, `html`.
- `--output FILE` — write output to a file, format inferred from extension (`.json`, `.sarif`, `.html`).
  Can be specified multiple times. If the extension isn't recognized, error out.

Examples:
```
skillsaw                                          # text to stdout (default)
skillsaw --format json                            # json to stdout
skillsaw --format json --output report.sarif      # json to stdout + sarif to file
skillsaw --output results.json --output r.html    # text to stdout + json + html to files
```

## No breaking changes

`Linter.run()` continues to return `List[RuleViolation]`. No new dataclasses.
Formatters receive the raw ingredients: `context`, `rules`, `violations`, `verbose`.
Stats are derived from what already exists:

- `context.repo_type` — repository type
- `context.plugins` — list of plugin paths (len = count)
- `context.skills` — list of skill paths (len = count)
- `linter.rules` — list of rules that ran (len = count)

With `-v`, JSON format includes the full lists (plugin paths, skill paths, rule IDs)
so callers can see exactly what was scanned, not just counts.

## Formatters

New module: `src/skillsaw/formatters/` with:

- `__init__.py` — `format_report()` dispatcher + `EXTENSION_MAP` + `infer_format()`
- `text.py` — current `Linter.format_results()` logic extracted here, with stats added
- `json_fmt.py` — JSON serialization
- `sarif.py` — SARIF v2.1.0 output (no external deps, just dict→json)
- `html.py` — self-contained HTML with inline CSS

### Text format

Same as current output, plus a "Scanned:" section always shown:
```
Scanned:
  Repo type: marketplace
  Plugins:   5
  Skills:    3
  Rules run: 12

Summary:
  Errors:   0
  Warnings: 0

✓ All checks passed!
```

### JSON format

```json
{
  "version": "0.4.3",
  "stats": {
    "repo_type": "marketplace",
    "plugins": 5,
    "skills": 3,
    "rules_run": 12
  },
  "violations": [],
  "summary": { "errors": 0, "warnings": 0, "info": 0 }
}
```

With `-v`, `stats` expands:
```json
{
  "stats": {
    "repo_type": "marketplace",
    "plugins": ["plugins/foo", "plugins/bar"],
    "skills": ["skills/baz"],
    "rules_run": ["plugin-json-required", "plugin-json-valid", "..."]
  }
}
```

### SARIF format

SARIF v2.1.0 — no external library, just dict→json:
- `runs[0].tool.driver.name`: "skillsaw", `.version`: skillsaw version
- `runs[0].tool.driver.rules[]`: one entry per rule that ran
- `runs[0].results[]`: one per violation with `ruleId`, `level`, `message.text`,
  `locations[].physicalLocation` (artifactLocation + region with startLine)
- `runs[0].properties.stats`: custom property bag with scan stats

### HTML format

Self-contained single-file HTML with inline CSS:
- Header with skillsaw version and repo type
- Stats summary
- Violations table grouped by severity (color-coded)
- Success/failure banner

## Files to create/modify

| File | Change |
|------|--------|
| `src/skillsaw/formatters/__init__.py` | **New** — dispatcher, extension map, `infer_format()` |
| `src/skillsaw/formatters/text.py` | **New** — extracted from `Linter.format_results()` |
| `src/skillsaw/formatters/json_fmt.py` | **New** — JSON formatter |
| `src/skillsaw/formatters/sarif.py` | **New** — SARIF v2.1.0 formatter |
| `src/skillsaw/formatters/html.py` | **New** — HTML formatter |
| `src/skillsaw/linter.py` | Remove `format_results()` and `get_counts()` (moved to formatters) |
| `src/skillsaw/__main__.py` | Add `--format`/`--output` args; use formatter dispatcher |
| `tests/test_linter.py` | Remove `format_results`/`get_counts` tests (moved) |
| `tests/test_formatters.py` | **New** — tests for all four formatters |
| `.github/workflows/test.yml` | Integration tests use `--format json` and assert stats |

## Integration test updates

```yaml
- name: Test ai-helpers repo
  run: |
    git clone https://github.com/openshift-eng/ai-helpers.git /tmp/ai-helpers
    skillsaw --format json /tmp/ai-helpers | python3 -c "
    import sys, json
    r = json.load(sys.stdin)
    assert r['stats']['plugins'] > 0, 'no plugins scanned'
    assert r['stats']['rules_run'] > 0, 'no rules ran'
    print(f\"Scanned {r['stats']['plugins']} plugins, {r['stats']['skills']} skills, {r['stats']['rules_run']} rules\")
    "

- name: Test auth0/agent-skills repo
  run: |
    git clone https://github.com/auth0/agent-skills.git /tmp/agent-skills
    skillsaw --format json /tmp/agent-skills | python3 -c "
    import sys, json
    r = json.load(sys.stdin)
    assert r['stats']['rules_run'] > 0, 'no rules ran'
    print(f\"Scanned {r['stats']['plugins']} plugins, {r['stats']['skills']} skills, {r['stats']['rules_run']} rules\")
    "
```

## Verification

1. `make test` — all tests pass
2. `make lint` — formatting clean
3. Manual: `skillsaw --format json` on this repo
4. Manual: `skillsaw --format sarif` — validate output structure
5. Manual: `skillsaw --output report.html` — open in browser
6. Manual: `skillsaw --output r.json --output r.sarif --output r.html` — all created
7. `make update` — regenerate docs
8. Test against `openshift-eng/ai-helpers` and `auth0/agent-skills`
