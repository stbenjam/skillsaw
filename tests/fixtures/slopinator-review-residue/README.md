# slopinator-review-residue

A small repo that contains, on purpose, what the Slopinator Reviewer is meant
to catch — and, beside it, what the reviewer must leave alone.

| File | Role |
|---|---|
| `src/catalog.py` | Review-history residue in code. Every comment is an instance of a Part A pattern. |
| `src/renderer.py` | Clean counterpart. Genuine "why" comments, including a long one that earns its length. |
| `tests/catalog_test.py` | Round-numbered test sections, plus verbose-but-accurate names that must stay. |
| `docs/overview.md` | Part B prose tells, clustered as they occur in generated prose. |
| `docs/reference.md` | Clean prose: domain vocabulary, house-style bold bullets, one correctly used em dash. |
| `CHANGELOG.md` | A version-scoped document, where narrating change is correct. |

The test file uses the `*_test.py` convention so this repo's pytest config
(`python_files = ["test_*.py"]`) does not collect fixture material as real
tests.

## What this fixture does and does not verify

`tests/test_review_panel_skill.py` asserts that every pattern named in
`references/slopinator.md` has a concrete instance here, and that the clean
files contain none of the residue markers. That keeps the scope file and this
fixture from drifting apart: adding a pattern to the scope file without adding
an example here fails the suite, and vice versa.

It does **not** verify that the reviewer actually catches them. The panel is a
prompt executed by an LLM, so a true end-to-end check needs a model in the
loop and cannot run in the unit suite. Point a live panel run at this
directory to check recall and precision by hand:

```bash
/skillsaw-review-panel   # from a branch whose diff includes these files
```

A reviewer that flags anything in `src/renderer.py`, `docs/reference.md`, or
`CHANGELOG.md` is miscalibrated.
