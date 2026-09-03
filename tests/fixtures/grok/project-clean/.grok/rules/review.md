# Review notes

- A migration and the code that reads its columns ship in the same pull
  request, never in two.
- Public API changes need an entry in `CHANGELOG.md` under `Unreleased`.
- If a test is skipped, the skip carries the issue number that will
  unskip it.
