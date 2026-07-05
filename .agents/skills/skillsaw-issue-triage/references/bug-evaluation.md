# Bug Evaluation — Checklist

A bug report claims skillsaw behaves incorrectly. Your job is to confirm or
refute that claim against the current code, then enrich the report.

## Reproduce first

- Build the smallest input that should trigger the claimed behavior: the config
  (`.skillsaw.yaml` / `.claudelint.yaml`), the file(s) being linted, and the
  exact command. Use the reporter's paste if they gave one; otherwise construct
  a minimal case from their description.
- Run it against the current tree:
  `.venv/bin/skillsaw lint <path>` (or `fix` for autofix bugs).
- Record observed vs. expected output verbatim. If it does not reproduce, say so
  and show what you ran — do not confirm a bug you could not trigger.

## Verify accuracy against the code

- **Locate the responsible code.** Trace the report to whatever owns the
  behavior — a rule under `src/skillsaw/rules/builtin/`, or the engine around it:
  the lint tree, `markdown_doc`, config discovery and loading, the autofix pass,
  `utils.py` read paths, or the CLI. For crashes, get the traceback and name the
  failing function wherever it lives.
- **Intended vs. defective.** Confirm the behavior is actually wrong, not working
  as designed. For a rule, check its docs (`skillsaw explain <rule-id>` /
  `skillsaw.org/rules/`) and its `default_severity` / `repo_types`; for engine
  behavior, check the relevant module and tests.
- **Classify the defect**: false positive, false negative, crash, wrong
  line/column, corrupting or non-idempotent autofix, or config/discovery bug.
- **Autofix bugs are high-signal** — check idempotency (running `fix` twice) and
  that the fix is scoped to the violation's span, not a broad `str.replace`.
- **Regression check**: does it reproduce on `main` too, or only on a branch?
  If a fix lands, a regression test is required.

## Severity signals

- Crashes, corrupting autofixes, and false positives on valid files that would
  break existing users' CI are the most severe.
- False negatives (a missed violation) matter but rarely block.

## Enrichment to add

- The minimal repro you settled on (config + input + command + observed/expected).
- The rule ID and `file:line` of the likely cause.
- The version/commit you verified against and whether `main` still reproduces.
- Any related issue or open PR (`gh pr list --search "<keywords>"`).
- Whether a fix would need a fixture under `tests/fixtures/` for regression cover.
