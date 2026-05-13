# Skillsaw TODO

Work items derived from the [ecosystem survey](docs/ecosystem-survey-2026-05-13.md)
of 45 repositories (~2,100 skills).

## Definition of Done

An item is complete when **all** of the following are true:

1. **Implemented** — code changes are on a branch
2. **Full test coverage** — new and changed behavior has tests, `make test` passes
3. **PR is open** — pushed and PR created via `gh pr create`
4. **CodeRabbit feedback addressed** — monitor the PR, review CodeRabbit comments through potentially several rounds, and resolve all feedback before marking done

## How to Work on This

Each `##` section below is **one subagent, one branch, one PR**. All items
under a heading are implemented together. Sections are independent and can be
worked on in parallel.

## Rule Improvements

- [ ] **Fix `content-negative-only` scope boundary false positives** — Skip patterns like "don't use (this) when:" headings that are scoping instructions, not purely negative content. Fix in `content_rules.py`.

- [ ] **Reduce `content-weak-language` severity for reference files** — `skill-ref` content blocks are supplementary material where hedging language is appropriate. Lower severity or skip for reference blocks in `content_rules.py`.

- [ ] **Add default exclude patterns to config** — Populate `exclude_patterns` in `LinterConfig.default()` with sensible defaults (`template/**`, etc.) so new configs ship with standard exclusions. Fix in `src/skillsaw/config.py`.

## New Rules

- [ ] **Add `content-broken-internal-reference` rule** — Detect markdown links pointing to nonexistent files. 99% precision, found 184 broken references across 45 repos. New rule in `content_rules.py`.

- [ ] **Add `content-unlinked-internal-reference` rule** — Detect bare path-like strings in markdown not wrapped in links. Matching controlled by `patterns` config, which defaults to `["./**/*.*", "references/**/*.md"]`. Users can extend or override. 95% precision, found 390 instances across 45 repos. New rule in `content_rules.py`.
  ```yaml
  rules:
    content-unlinked-internal-reference:
      patterns:
        - "./**/*.*"
        - "references/**/*.md"
  ```

- [ ] **Add `content-placeholder-text` rule** — Detect TODO markers, `[link here]`, and unfilled template placeholders left in published skills. New rule in `content_rules.py`.

## Rule Suppression

- [ ] **Add per-rule `excludes` in config** — Every rule accepts an `excludes` list of glob patterns in `.skillsaw.yaml` to skip specific files/paths. Patterns use the same `fnmatch` semantics as the top-level `exclude_patterns`. Check during rule dispatch before `check()` runs. See [design doc](docs/ecosystem-survey-2026-05-13.md#design-rule-suppression).
  ```yaml
  rules:
    content-weak-language:
      excludes:
        - "skills/legacy/**"
  ```

- [ ] **Add inline HTML comment directives** — Support `<!-- skillsaw-disable rule-id -->` / `<!-- skillsaw-enable -->` and `<!-- skillsaw-disable-next-line rule-id -->` in markdown content. Parse during content block extraction, maintain a suppression stack per block. See [design doc](docs/ecosystem-survey-2026-05-13.md#design-rule-suppression).

## Documentation & Config

- [ ] **Add rule doc text to generated config** — Extract short descriptions for each rule into the generated `.skillsaw.yaml` as comments, along with commented-out configuration options where the rule accepts parameters. Update config generation in `src/skillsaw/config.py`.
