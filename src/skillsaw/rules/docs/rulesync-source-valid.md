Checks conventional `.rulesync/rules/**/*.md` frontmatter and common
`rulesync.jsonc` field shapes against Rulesync 32.0.0. The check is opt-in and
does not attempt to validate every target or compiler feature.

## How to fix

Start rule files with YAML frontmatter delimited by `---`. Use booleans for
`root`, `localRoot`, and `cursor.alwaysApply`; arrays of strings for `targets`,
`globs`, and target-specific path lists; and a string for `description`.
Optional null frontmatter values are treated as absent, matching Rulesync.

Use a JSONC object for project configuration. Choose `inputRoot` or `inputRoots`.
Use an array of strings for `features`, or put per-target feature selections
under object-form `targets` and omit `features`.
Rulesync's own validation remains responsible for target/feature names,
per-target options, and frontmatter extensions outside the documented subset.
Timestamp and binary mapping-key coercion is outside that subset; timestamp
collisions depend on the generator's runtime time zone. Such sources do not
confer generated ownership, and their emitted files retain all consumer checks.
Quote date-like keys when they are intended as literal strings.

Generate explicitly, then lint the resulting native consumer files. Enable
`rulesync-generated: true` only when Rulesync owns the configured conventional
modular outputs. See the [generator workflow](https://skillsaw.org/generators/)
for exact copy-recognition limits and pinned compatibility evidence.
