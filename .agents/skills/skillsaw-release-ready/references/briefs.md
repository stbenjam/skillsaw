# Briefs for reviewers and auditors

Write two brief files under `~/tmp/skillsaw-audit/briefs/` and tell every
agent to read its brief first. Prompts then carry only the item-specific
part: the rule or dimension, the files, the oracle to install, and the
shapes to probe.

## Rule reviewer

One Opus subagent per rule added since the last tag. Read-only on the
repository; scratch under `~/tmp/skillsaw-audit/work/<rule-id>/`. Required
work, in order:

1. Read the rule, its doc, its tests, and the development rules; flag every
   convention the rule breaks.
2. Fetch the upstream spec and compare every check against what the tool
   accepts. A check stricter than the tool is a false-positive generator.
3. Run the rule on the shared corpus plus repositories it finds itself,
   classify every finding as true, false, or debatable, and give a
   `file:line` and the reason for every false one.
4. Probe with valid-but-unusual fixtures: alternate syntaxes, scalar versus
   list, optional fields, nested layouts, monorepos, Windows paths, Unicode,
   empty files, future schema versions. Malformed input must produce a
   finding, never a traceback. Run the autofix twice.
5. Check discovery: does the tree attach the files in real layouts, and does
   it avoid `node_modules` and vendored content?
6. Check the message and doc against the real behavior.
7. Time the rule on the largest corpus repository.
8. Note duplicated helpers and inconsistency with sibling rules.

Report to `reports/rule-<id>.md`: verdict (SHIP, SHIP-WITH-FIXES, HOLD), a
corpus table, numbered findings with severity P0 to P3, category, evidence,
why it matters by the three questions, and a suggested fix; then "things I
checked that are fine" and "beyond release". Final message under 40 lines.

## Dimension auditor

One subagent per dimension, same scratch rules, same report shape under
`reports/audit-<dimension>.md` with a health verdict out of five and the
single biggest risk. Dimensions that paid for themselves:

- core architecture: layering rules, tree build stages, memoization and
  cache invalidation, interface consistency, Python floor.
- rules layer: duplication across ecosystem packages, naming and message
  conventions, `since`, defaults, config schema, doc drift.
- CLI and UX: every subcommand and flag actually run on corpus repositories,
  exit codes, output formats validated against their schemas.
- performance: last release versus head on the same repositories and
  interpreter, profiles of the slowest, algorithmic smells in new code.
- modified-rules regression: differential lint of every changed existing
  rule, last release versus head, over the corpus.
- real-world sweep: every corpus repository under default config, every
  rule force-enabled, every `--type`, `fix` on copies twice; crash list
  first, then per-rule volume with sampled precision.
- security: containment, symlinks, hostile YAML and JSON, ReDoS with a
  timeout harness, network I/O, the feedback bundle.
- tests and quality: coverage of new code, order dependence, fixture
  realism, `make update` clean in a fresh worktree.
- docs and release: CLI docs versus `--help`, rule docs versus source,
  site build strict, and a draft of the release notes.
