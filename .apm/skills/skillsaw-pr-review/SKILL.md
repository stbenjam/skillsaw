---
name: skillsaw-pr-review
description: Review open PRs in skillsaw, fix failing CI, address reviewer feedback, and push updates. Use for triaging and fixing up existing pull requests.
compatibility: Requires git, gh CLI, and internet access
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw PR Review

You are reviewing and fixing up open pull requests in the **skillsaw** linter.

## Step 1: List open PRs

Use `gh pr list --state open` to find all open PRs in this repo.

## Step 2: For each open PR

Check out the PR branch and:

1. **Check CI status** — run `gh pr checks <number>`
   - If checks are failing, investigate the failure
   - Read the test output, trace the root cause
   - Fix the issue on the PR branch
   - Run the full test suite locally: `pytest tests/ -v`
   - Run formatting: `black src/ tests/`
   - Push the fix

2. **Check for review comments** — run `gh pr view <number> --comments`
   - If there is reviewer feedback, address it
   - Make the requested changes on the PR branch
   - Run tests and formatting
   - Push the changes

3. **Validate backward compatibility**
   - Test against ai-helpers: clone `openshift-eng/ai-helpers`, run `skillsaw` against it, ensure exit 0
   - Ensure no existing tests break

## Important constraints

- Never introduce breaking changes to the config format
- The `claudelint` CLI shim and `from claudelint import ...` must continue working
- Config discovery must continue finding `.claudelint.yaml` as a fallback
- All rule IDs are stable — never rename an existing rule ID
- When pushing fixes, add `[Auto]` prefix to any new commit messages
