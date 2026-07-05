# Review Guidelines

Guidance for automated reviewers (Devin) on pull requests to skillsaw.

skillsaw is a configurable, rule-based linter and autofixer for agentic
context files (CLAUDE.md, plugin manifests, skill definitions, hooks, MCP
configs). It runs as a local dev tool and in CI, reads potentially
adversary-controlled repository content, and can rewrite files. Two things
matter most in review: the change is **coherent with existing conventions**,
and it introduces **no security-risk patterns**.

The canonical conventions live in `.apm/instructions/`, `CONTRIBUTING.md`, and
`DEVELOPMENT.md`; the security posture lives in
[THREAT_MODEL.md](THREAT_MODEL.md). This file is the review checklist derived
from them — flag deviations.

## Codebase coherence

### Lint rules

- New rules must **register themselves** — any concrete `Rule` subclass under
  `src/skillsaw/rules/builtin/` is auto-discovered. Flag hand-maintained
  import lists or config dicts.
- New rules must default to `enabled: auto` or `enabled: false`
  (`default_enabled`). Flag anything that force-enables a new rule — it breaks
  existing users on upgrade.
- Never change behavior that breaks existing rules for current users. A rule
  becoming stricter, or a default flipping, needs explicit justification.
- Rules that report a specific location must **report a line number**
  (whole-file and JSON rules are exempt). Never fabricate a line number — omit
  it when the field is absent.
- YAML must be read with `read_yaml_commented()` (from `utils.py`), never
  `yaml.safe_load()` or `read_yaml()` in rule code; line numbers come from
  `commented_key_line()` / `commented_item_line()`.
- Prose vs config is encoded in the block hierarchy: prose files subclass
  `ContentBlock`, structured config (settings, hooks, MCP JSON) subclass
  `JsonConfigBlock`. Flag any config file type added under `ContentBlock` —
  content rules would lint its JSON as instruction text.
- Everything the rule inspects should come from the parse tree
  (`context.lint_tree.find(NodeType)`), not ad-hoc file reads.

### Markdown: AST for reading, splice for writing

- Markdown structure (links, code spans, fences, headings, HTML comments)
  comes from the markdown-it-py AST via `block.markdown` (`MarkdownDoc`). Flag
  hand-rolled per-line regexes for markdown structure.
- Fixes must splice at the token spans the check matched
  (`markdown_doc.splice(...)`). Flag fixes that re-locate targets with
  `line.find()` / `str.replace()` — they corrupt substrings of other tokens.
- Never render the AST back to markdown (round-trip reformats the whole file
  and violates scope-the-fix).

### Autofix invariants

- No negative lookarounds around backtrackable quantifiers in patterns that
  feed autofixes — the engine backtracks into a truncated match and the fix
  splices a corrupted span (issue #321). Match greedily, reject by inspecting
  adjacent characters.
- A fix that adds a frontmatter field must guard against the key already
  existing (`replace_frontmatter_field()` first, then
  `prepend_frontmatter_fields()`), or it prepends a duplicate every run and
  never converges.
- Fixes must be scoped to the violation's line, be idempotent (running fix
  twice yields identical content), and not change line counts.

### Performance

When touching content rules, the lint tree, or `utils.py`:

- No per-line × per-pattern regex loops in scanning rules — run
  `patterns_matching_anywhere(body, patterns)` first and per-line scan only
  survivors.
- Whole-blob work (`.lower()`, config-file stats) belongs outside the
  per-block loop — compute once per `check()`.
- Anything that mutates tree structure outside a rebuild must call
  `invalidate_find_cache()` (`lint_tree.find` is memoized per node).

## Security-risk patterns to flag

skillsaw reads untrusted repository content and an untrusted `.skillsaw.yaml`.
Flag any change that widens these surfaces.

### Untrusted input: regex, deserialization, paths

- **Unbounded regex from config or file content (ReDoS, T13).** Any new place
  that compiles a repository- or config-supplied pattern and runs it against
  file content must run under the per-pattern wall-clock budget
  (`regex-timeout`, `SIGALRM`). Flag catastrophic-backtracking-prone patterns
  and any regex over untrusted input without a timeout.
- **Unsafe YAML or deserialization (T5).** Config and rule parsing must use
  `yaml.safe_load` / `YAML(typ='safe')` (or ruamel round-trip). Flag any
  `yaml.load` without a safe loader, `pickle`, `eval`, `exec`, or
  `__reduce__`-style deserialization on untrusted input.
- **Path traversal (T6).** Any path derived from repository-controlled input
  (marketplace `source`, config paths) must be confined to the repository root
  (`candidate.relative_to(self.root_path)` or equivalent) before reading. Flag
  path joins from untrusted fields that skip that check.

### CI gate, secrets, and supply chain

- **Custom-rule execution (T1).** Custom rules load via `exec_module` (arbitrary
  code by design). Any change here must preserve the `--no-custom-rules` gate,
  the Action's `--no-custom-rules` default, and the visible warning when custom
  rules load.
- **CI gate integrity (T4, T12).** Rule exceptions are caught per-rule so one
  bad rule cannot abort the run — but flag changes that could let a crash or a
  swallowed exception silently produce exit 0 (a false pass). Scrutinize edits
  to suppression, baseline, and exit-code logic.
- **`GITHUB_TOKEN` handling (T9).** In [action/review.py](action/review.py) the
  token is used only for comment API calls and never logged. Flag any code path
  that logs, echoes, or forwards it, or that broadens its use.
- **Secrets and command execution.** Flag `subprocess` with `shell=True` on
  untrusted input, secrets written to logs or artifacts, and any new network
  call (skillsaw makes none of its own).
- **New dependencies.** Flag added third-party dependencies — prefer the
  standard library; a new dependency expands the supply-chain surface (T8).
- **GitHub Actions workflows.** Flag unpinned actions (use commit SHAs),
  version ranges for pip installs in CI, and `pull_request_target` or other
  patterns that expose secrets to fork pull requests.

## Tests and docs

- New rules, flags, features, and lint types need integration test coverage in
  [tests/test_integration.py](tests/test_integration.py) **with static
  fixtures** under `tests/fixtures/` (realistic content, not one-liner stubs).
  Bug fixes need a regression test.
- Autofix tests must assert: fix scoped to the violation's line, line count
  unchanged, idempotent on a second run, and zero remaining violations on
  re-lint.
- User-facing changes (a new flag, rule, or lint type) must update
  `README.md`. Docs restructures must not break published URLs — flag
  moved or renamed doc pages that lack an mkdocs-redirects entry.
- Python must run through the project venv (`.venv/bin/...`) and `make`
  targets — flag bare `python` / `python3` invocations in scripts or CI.
