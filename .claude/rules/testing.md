# Testing

## Integration Tests

Integration tests live in `tests/test_integration.py` and verify end-to-end
behavior by running the CLI (`python -m skillsaw lint` / `fix`) against
realistic repo fixtures.

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
