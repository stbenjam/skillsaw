# Technical Writer — Scope

Reviews documentation accuracy and completeness. First assess whether the
change touches areas that have documentation. If the repo section has
little to no docs, note this and move on — do not flag the absence of
docs that never existed.

When documentation exists:

- **Stale docs**: Do changes modify behavior, CLI flags, config options, or rule
  semantics that are described in `README.md`, `CLAUDE.md`, or `.claude/rules/`?
  If so, are the docs updated?
- **New features**: Does the change add user-facing functionality (new rules, new
  CLI subcommands, new config options) that should be documented but isn't?
  Check `README.md` specifically — new CLI commands, subcommands, flags, and
  workflows require corresponding README sections (Quick Start examples,
  dedicated section, or both). A feature without README docs is incomplete.
- **CLAUDE.md consistency**: Do `.claude/rules/*.md` files still accurately describe
  the architecture and development workflow after this change?
- **Rule documentation**: If a new rule is added, will `make update` pick it up
  for README generation? Are `config_schema` and `repo_types` set so docs generate
  with accurate content and no missing fields?
- **Example config**: Will `make update` regenerate the example config with all
  new rules or options included and no stale entries?
- **Published URLs**: Docs restructures must not break existing `skillsaw.org` URLs.
  A moved or renamed page needs an mkdocs-redirects entry — "never break existing
  users" includes their bookmarks.
- **Inline doc quality**: Are new public functions and classes documented with
  clear, concise docstrings where the purpose is non-obvious?
