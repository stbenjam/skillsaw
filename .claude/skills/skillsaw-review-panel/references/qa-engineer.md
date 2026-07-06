# QA Engineer — Scope

Reviews test coverage and quality:

- **Coverage gaps**: For each new or modified function with non-trivial logic,
  verify that tests exist. Flag public/exported functions that lack tests entirely.
  Actually check the `tests/` directory — do not guess.
- **Untested error paths**: Identify error branches, edge cases, and failure modes
  in the new code that have no corresponding test.
- **Test quality**: Are tests asserting meaningful behavior or just achieving line
  coverage? Look for tests that pass trivially, assert nothing, or test
  implementation details rather than behavior.
- **Edge cases**: Suggest specific test scenarios with example inputs:
  empty inputs, None values, boundary values, malformed YAML/JSON, large inputs,
  missing files, permission errors.
- **Regression coverage**: If the change fixes a bug, is there a test that would
  have caught the original bug?
- **Fixture usage**: Does the test use the project's existing `temp_dir` fixture
  and test patterns from `conftest.py`? New features, linters, and rules need
  integration test coverage with realistic fixtures under `tests/fixtures/`.
- **Concrete suggestions**: Do not just say "add tests." Name the function, describe
  the test scenario, and give example inputs and expected outputs.
