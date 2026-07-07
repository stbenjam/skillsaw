# Review Guidelines

Use this guidance to review PRs to skillsaw (for automated reviewers such as Devin).

Review each PR knowing what skillsaw is: a configurable, rule-based linter and
autofixer for agentic context files (`CLAUDE.md`, plugin manifests, skill
definitions, hooks, MCP configs). It runs locally and in CI, reads
adversary-controlled repo content, and can rewrite files. Keep every change
**coherent with existing conventions** and ensure it adds **no security-risk patterns**.

Read the canonical conventions in `.apm/instructions/`, `CONTRIBUTING.md`, and
`DEVELOPMENT.md`; read the security posture in [THREAT_MODEL.md](THREAT_MODEL.md).
Review each change against the checklist below and always flag deviations.

## Repo coherence

### Lint rules

- Check that new rules **register themselves**: any concrete `Rule` subclass under `src/skillsaw/rules/builtin/` is auto-discovered. Flag hand-maintained import lists or config dicts.
- Check that new rules default to `enabled: auto` or `enabled: false` (`default_enabled`); flag anything that force-enables a new rule — it breaks existing users on upgrade.
- Never change behavior that breaks existing rules for current users — a rule becoming stricter, or a default flipping, needs explicit justification.
- Ensure rules that report a specific location **report a line number** (whole-file and JSON rules are exempt); never fabricate one — omit it when the field is absent.
- Check that rule code reads YAML with `read_yaml_commented()` (from `utils.py`), never `yaml.safe_load()` or `read_yaml()`; line numbers come from `commented_key_line()` / `commented_item_line()`.
- Check that prose vs config follows the block hierarchy: prose files subclass `ContentBlock`, structured config (settings, hooks, MCP JSON) subclass `JsonConfigBlock`. Flag any config file type added under `ContentBlock` — content rules would lint its JSON as instruction text.
- Ensure everything the rule inspects comes from the parse tree (`context.lint_tree.find(NodeType)`), not ad-hoc file reads.

### Markdown: AST for reading, splice for writing

- Check that markdown structure (links, code spans, fences, headings, HTML comments) comes from the markdown-it-py AST via `block.markdown` (`MarkdownDoc`); flag hand-rolled per-line regexes for markdown structure.
- Ensure fixes splice at the token spans the check matched (`markdown_doc.splice(...)`); flag fixes that re-locate targets with `line.find()` / `str.replace()` — they corrupt substrings of other tokens.
- Never render the AST back to markdown — round-trip reformats the whole file and violates scope-the-fix.

### Autofix invariants

- Avoid negative lookarounds around backtrackable quantifiers in patterns that feed autofixes — the engine backtracks into a truncated match and the fix splices a corrupted span (issue #321); match greedily, then reject by inspecting adjacent characters.
- Verify that a fix adding a frontmatter field guards against the key already existing (`replace_frontmatter_field()` first, then `prepend_frontmatter_fields()`), or it prepends a duplicate every run and never converges.
- Ensure fixes stay scoped to the violation's line, keep idempotent (running fix twice yields identical content), and never change line counts.

### Performance

Review these when touching content rules, the lint tree, or `utils.py`:

- Avoid per-line × per-pattern regex loops in scanning rules — run `patterns_matching_anywhere(body, patterns)` first and per-line scan only survivors.
- Keep whole-blob work (`.lower()`, config-file stats) outside the per-block loop — compute it once per `check()`.
- Ensure anything that mutates tree structure outside a rebuild calls `invalidate_find_cache()` (`lint_tree.find` is memoized per node).

## Security-risk patterns to flag

Review every change against these surfaces: skillsaw reads untrusted repo content and an untrusted `.skillsaw.yaml` — flag anything that widens them.

### Untrusted input: regex, deserialization, paths

- Check **unbounded regex from config or file content (ReDoS, T13)**: any new place that compiles a repo- or config-supplied pattern and runs it against file content must run under the per-pattern wall-clock budget (`regex-timeout`, `SIGALRM`). Flag catastrophic-backtracking-prone patterns and any regex over untrusted input without a timeout.
- Check **unsafe YAML or deserialization (T5)**: config and rule parsing must use `yaml.safe_load` / `YAML(typ='safe')` (or ruamel round-trip). Flag any `yaml.load` without a safe loader, `pickle`, `eval`, `exec`, or `__reduce__`-style deserialization on untrusted input.
- Check **path traversal (T6)**: confine any path derived from repo-controlled input (marketplace `source`, config paths) to the repo root (`candidate.relative_to(self.root_path)` or equivalent) before reading. Flag path joins from untrusted fields that skip that check.

### CI gate, secrets, and supply chain

- Check **custom-rule execution (T1)**: custom rules load via `exec_module` (arbitrary code by design). Ensure any change here preserves the `--no-custom-rules` gate, the Action's `--no-custom-rules` default, and the visible warning when custom rules load.
- Check **CI gate integrity (T4, T12)**: rule exceptions are caught per-rule so one bad rule cannot abort the run — flag changes that could let a crash or a swallowed exception silently produce exit 0 (a false pass). Review edits to suppression, baseline, and exit-code logic.
- Check **`GITHUB_TOKEN` handling (T9)**: in [action/review.py](action/review.py) the token is used only for comment API calls and never logged. Flag any code path that logs, echoes, or forwards it, or that broadens its use.
- Review **secrets and command execution**: flag `subprocess` with `shell=True` on untrusted input, secrets written to logs or artifacts, and any new network call (skillsaw makes none of its own).
- Check **new dependencies**: flag added third-party dependencies — prefer the standard library; a new dependency expands the supply-chain surface (T8).
- Check **GitHub Actions workflows**: flag unpinned actions (use commit SHAs), version ranges for pip installs in CI, and `pull_request_target` or other patterns that expose secrets to fork PRs.

## Tests and docs

- Ensure new rules, flags, features, and lint types include integration test coverage in [tests/test_integration.py](tests/test_integration.py) **with static fixtures** under `tests/fixtures/` (realistic content, not one-liner stubs). Bug fixes need a regression test.
- Verify autofix tests assert: fix scoped to the violation's line, line count unchanged, idempotent on a second run, and zero remaining violations on re-lint.
- Ensure user-facing changes (a new flag, rule, or lint type) update `README.md`. Docs restructures must not break published URLs — flag moved or renamed doc pages that lack an mkdocs-redirects entry.
- Ensure Python runs through the project venv (`.venv/bin/...`) and `make` targets — flag bare `python` / `python3` invocations in scripts or CI.
