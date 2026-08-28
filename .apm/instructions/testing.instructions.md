---
description: Guidelines for writing tests, especially integration tests with fixtures
---

<!-- Source paths below are repo-root-relative references, not links navigable from this file's directory. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

# Testing

## Integration Tests

Integration tests live in `tests/test_integration.py` and verify end-to-end
behavior by driving the CLI (`skillsaw lint` / `fix`) against realistic repo
fixtures.

### Drive the CLI through `run_cli`

`run_lint` and the `_run_fix` helpers call `run_cli` from
`tests/cli_runner.py`, which invokes `skillsaw.cli.main()` in-process with
argv, stdout, stderr, env and cwd swapped, and returns a
`subprocess.CompletedProcess` stand-in. Spawning an interpreter per call cost
~160ms — more than half of it importing skillsaw — and dominated the suite.
Prefer `run_cli` for a new integration test.

Reach for a real `subprocess.run` only when the test depends on something a
shared interpreter cannot give it:

- **Import isolation** — the `--no-custom-rules` tests prove a rule file on
  disk did or did not get imported. In-process they would execute an
  arbitrary rule inside the test worker, and `sys.modules` could mask a
  repeat import and make the negative case pass vacuously.
- **A real encoding on stdout** — the lone-surrogate regressions assert that
  rendering a report raises no `UnicodeEncodeError`. A `StringIO` never
  encodes, so in-process they would pass vacuously.
- **TTY and colour-cascade behavior**, which depends on the real stream.
- **Entry-point discovery** — `tests/test_integration_plugins.py` installs
  plugins and needs a fresh interpreter to pick them up, so it stays on
  subprocess throughout.

Anything `run_cli` runs shares one interpreter, so a helper that leaves
process-global state behind breaks later tests. `run_cli` already resets the
two that outlive a call — root logging handlers and the `skillsaw.utils` file
cache; add to `_reset_process_globals` if you introduce another.

### Use test fixtures

Prefer static fixtures in `tests/fixtures/` over building repos
programmatically in test code. Fixtures should contain realistic file content
that mirrors what real users would write.

- Create a directory under `tests/fixtures/` with the files needed for the test
- Use `copy_fixture(name, tmp_path)` to copy into a temp directory before running
- Keep fixture CLAUDE.md files realistic — not one-liner stubs

### Autofix tests

When testing autofix behavior:

- Scope the fix to the violation's line — never apply regex or `str.replace()`
  across the entire file content, as this can match the wrong occurrence.
- Verify that line counts do not change after autofix (wrapping text in link
  syntax, for example, should not add or remove lines).
- Test idempotency: running fix twice should produce identical content.
- Re-lint after fix to confirm zero remaining violations for the rule under test.
