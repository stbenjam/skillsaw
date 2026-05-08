---
name: skillsaw-review-panel
description: Serial multi-specialist code review panel for skillsaw PRs. Runs 5 specialist reviewers (Architecture, Python Expert, Security & Supply Chain, QA Engineer, Technical Writer) inline then synthesizes a single verdict.
compatibility: Requires git, gh CLI, and internet access
metadata:
  author: stbenjam
  version: "1.0"
---

# Review Panel — Serial Multi-Specialist Review

Run **5 specialist reviewers + 1 arbiter** inline in the main agent, one
after another. This is serial-only by design — the codebase context is
derived once and shared across all specialists, saving tokens. Each
specialist can see prior specialists' file reads (though not their
findings).

The panel is **advisory**. It does not gate merge. It surfaces findings;
the maintainer and PR author decide ship.

## Specialist Roster

| Specialist | Lens |
|---|---|
| Architecture Reviewer | Module boundaries, abstraction level, SOLID, cross-file impact, error propagation |
| Python Expert | Idiomatic Python, type hints, performance, stdlib usage, packaging conventions |
| Security & Supply Chain Reviewer | Injection, credential handling, dependency trust, lockfile integrity, build pipeline |
| QA Engineer | Test coverage gaps, untested error paths, edge cases, concrete test suggestions |
| Technical Writer | Documentation accuracy, completeness, consistency with code changes, CLAUDE.md drift |
| Panel Arbiter | Strategic synthesis, disagreement resolution, final disposition |

## Specialist Scope

### Architecture Reviewer

Reviews structural quality of the change:

- **Single Responsibility**: Does each new function/type/module have one clear job?
- **Cross-file impact**: Do changes ripple correctly through callers and dependents?
  Trace imports from changed modules to verify no downstream breakage.
- **Abstraction level**: Are new abstractions justified or premature? Three similar
  lines is better than a premature abstraction.
- **Module boundaries**: Are package/module imports clean? Any circular dependencies?
  Does the change respect the existing architecture (context.py -> config.py ->
  rule.py -> linter.py pipeline)?
- **Error handling**: Are errors propagated correctly? No swallowed errors? Exceptions
  should carry actionable messages.
- **Pattern consistency**: Do new patterns match existing architectural conventions
  in the codebase?

Anti-patterns to flag: god functions, shotgun surgery, feature envy,
inappropriate intimacy, premature abstraction.

### Python Expert

Reviews Python-specific quality:

- **Idiomatic Python**: Does the code use Python idioms correctly? List comprehensions
  vs loops, context managers, f-strings, pathlib over os.path, dataclasses where
  appropriate.
- **Type hints**: Are new public functions properly typed? Do type hints match actual
  behavior? Are `Optional`, `Union`, generic types used correctly?
- **Performance**: Any obvious O(n^2) patterns, unnecessary copies, repeated I/O in
  loops, or wasteful allocations? For a linter codebase, file I/O patterns matter.
- **stdlib usage**: Is the code reinventing something available in the standard library?
  Check `pathlib`, `dataclasses`, `functools`, `itertools`, `contextlib`, `typing`,
  `importlib.resources`, `json`, `re`, `argparse`.
- **Packaging**: Are `pyproject.toml` changes correct? Are package-data patterns right?
  Are imports structured so that `skillsaw` and the `claudelint` shim both work?
- **Compatibility**: Does the code work on Python 3.9+? Avoid walrus operator patterns
  that assume 3.10+ match statement syntax.

### Security & Supply Chain Reviewer

Reviews security posture with a **fails-closed** bias — when uncertain
whether a pattern is safe, flag it.

**Vulnerability surfaces:**
- **Injection**: Command injection via subprocess, template injection, log injection.
  Any use of `subprocess` with `shell=True` or unsanitized user input in commands
  is blocking.
- **Path traversal**: Does user-supplied input flow into file paths without validation?
  Check `Path()` constructions from external input.
- **Secret management**: Hardcoded secrets, secrets in logs, config exposure.
- **Input validation**: Untrusted input at system boundaries. For skillsaw, this means
  plugin.json, marketplace.json, SKILL.md, and other files the linter parses — a
  malicious repo could craft these to exploit the linter.

**Supply chain risk:**
- **New dependencies**: Is the dependency necessary? Actively maintained? How many
  transitive dependencies does it pull in?
- **Dependency changes**: Version bumps, removed pins, loosened constraints.
- **Build pipeline changes**: CI config, Makefile, Dockerfile, GitHub Actions workflows.
  Do they introduce untrusted sources or execution of remote code?
- **GitHub Actions**: Are action versions pinned to commit SHAs or at least major
  versions? Any use of `pull_request_target` with checkout of PR code?

### QA Engineer

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
  and test patterns from `conftest.py`?
- **Concrete suggestions**: Do not just say "add tests." Name the function, describe
  the test scenario, and give example inputs and expected outputs.

### Technical Writer

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
  workflows MUST have corresponding README sections (Quick Start examples,
  dedicated section, or both). A feature without README docs is incomplete.
- **CLAUDE.md consistency**: Do `.claude/rules/*.md` files still accurately describe
  the architecture and development workflow after this change?
- **Rule documentation**: If a new rule is added, will `make update` pick it up
  for README generation? Are `config_schema` and `repo_types` set so docs generate
  correctly?
- **Example config**: Will `make update` regenerate the example config correctly
  with any new rules or options?
- **Inline doc quality**: Are new public functions and classes documented with
  clear, concise docstrings where the purpose is non-obvious?

## Execution Procedure

Work through these steps in order. Do not skip ahead.

### Step 1 — Determine Base Ref and Read the Diff

Figure out what the changes are being compared against:

- If a PR number is provided: use `gh pr view <number> --json baseRefName` to
  get the base branch, then compute the merge base.
- If no PR number: find the merge base using the first of `upstream/main`,
  `origin/main`, `upstream/master`, `origin/master` that exists.

If no base ref can be determined, error and exit.

Check out the PR branch if not already on it:
```bash
gh pr checkout <number>
```

Read the diff once:
```bash
git diff <base-ref>...HEAD
```

Also run `git diff <base-ref>...HEAD --stat` for a file-level summary.

### Step 2 — Check for Prior Panel Reviews

When reviewing a PR, check for previous panel review comments:

```bash
gh pr view <number> --json comments --jq '.comments[] | select(.body | contains("Generated by skillsaw-review-panel")) | {createdAt, body}'
```

If prior reviews exist, note which findings have been addressed by
subsequent commits and which remain unresolved. Avoid re-raising
resolved issues.

### Step 3 — Run Specialists Serially

For each specialist in roster order (Architecture, Python Expert,
Security & Supply Chain, QA Engineer, Technical Writer):

1. State the specialist name as a heading.
2. Review the diff and codebase through that specialist's lens using
   the scope defined above. Read files, grep, and run git commands as
   needed — context from earlier specialists' file reads carries over.
3. Produce findings in this format:
   - **Severity**: `BLOCKING` | `SUGGESTION` | `NOTE`
   - **File:line** reference (when applicable)
   - **Finding** description
   - **Recommended action**
4. If no issues found, say so with what was checked.
5. Move on to the next specialist.

**Severity calibration:**
- `BLOCKING`: Correctness regressions, security vulnerabilities, architectural
  faults that compound. Must include explicit rationale for why this blocks.
- `SUGGESTION`: Substantive feedback that improves the code but is not a
  correctness issue. This is the default for real feedback.
- `NOTE`: One-line polish, style nits, minor improvements.

### Step 4 — Panel Arbiter Synthesis

After all specialists complete, synthesize directly:

1. Read all specialist findings
2. Resolve any conflicts between specialists
3. Assign disposition: **APPROVE**, **REQUEST_CHANGES**, or **NEEDS_DISCUSSION**
4. Compile required actions (blocking) vs optional follow-ups

**Disposition criteria:**

- **APPROVE**: No unresolved BLOCKING findings
- **REQUEST_CHANGES**: BLOCKING findings that require code changes
- **NEEDS_DISCUSSION**: Findings that need author input to resolve

**Arbiter biases:**

- Security over ergonomics
- Codebase consistency over local elegance
- Existing patterns over novel ones
- Backward compatibility is paramount — breaking existing users is always blocking

Clean changes with no issues are a valid outcome — do not manufacture
findings.

### Step 5 — Render and Post Verdict

Load `verdict-template.md` (same directory as this skill) and fill the
placeholders with findings and synthesis. Post the rendered verdict as
exactly ONE PR comment:

```bash
gh pr comment <number> --body "$(cat <<'VERDICT'
<rendered verdict>
VERDICT
)"
```

## Quality Gates

A change passes when:

- [ ] Architecture Reviewer: structure and patterns are sound
- [ ] Python Expert: idiomatic, well-typed, performant Python
- [ ] Security & Supply Chain: no unmitigated vulnerability or supply chain risk
- [ ] QA Engineer: adequate test coverage, edge cases addressed
- [ ] Technical Writer: documentation consistent with changes
- [ ] Panel Arbiter: trade-offs ratified, disposition set
