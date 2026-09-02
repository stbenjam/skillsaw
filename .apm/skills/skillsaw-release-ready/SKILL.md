---
name: skillsaw-release-ready
description: Audit skillsaw for release readiness — test new rules against real repositories, audit core architectural dimensions, independently verify proposed fixes, and ship improvements in clean, focused batches. Use before cutting a release.
compatibility: Requires git, gh CLI, uv, internet access, and subagents (Opus for reviewers). Uses ~/tmp for corpus storage.
license: Apache-2.0
user-invocable: true
metadata:
  author: stbenjam
  version: "1.0"
---

<!-- Source paths below are repo-root-relative references, not links navigable from this skill's directory. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

# skillsaw Release Ready

Ensure skillsaw is rock-solid before every release. This skill orchestrates parallel subagent reviews to test newly added rules against real-world repositories, audits key codebase dimensions, and ships vetted improvements in clean batches of up to 10 commits per PR.

Reviewers evaluate every finding using three core questions:

1. **Does it affect common usage?** Prioritize findings that developers will frequently encounter on real projects.
2. **Is it accurate?** Guard against false positives on files that upstream tools accept.
3. **Is it helpful and high-signal?** Ensure rules provide clear value without unnecessary noise.

## Step 1: Establish scope

Identify what has changed since the last release tag:

```bash
git fetch --tags
git diff --name-status v<last>..HEAD -- src/skillsaw/rules/builtin/ | grep -E '^[AM]'
git log --merges --format=%s v<last>..HEAD
gh pr view <n> --json title,body   # review previous release-readiness PRs
```

List new rule IDs, modified rules, and fixes that have already landed so reviewers can focus on unresolved areas.

## Step 2: Set up the audit workspace

- Use `~/tmp/skillsaw-audit/` for working files (`corpus/`, `reports/`, `briefs/`, `work/<agent>/`).
- Shallow-clone a representative corpus of real repositories into `corpus/` (see [corpus](references/corpus.md)).
- Install the previous release in `~/tmp/skillsaw-audit/venv-<last>/` to run comparative checks without touching the main development `.venv`.
- Use `skillsaw lint <path> --no-custom-rules --rule <id>` to test specific rules directly. Pass `--no-custom-rules` on every corpus scan: a cloned repository's `.skillsaw.yaml` can name Python files under `custom-rules`, and the linter would run them.

## Step 3: Launch reviewers and auditors

Launch reviewer subagents for new rules and dimension auditors in parallel. Each agent reviews shared guidelines in [briefs](references/briefs.md), writes its findings to `reports/<name>.md`, and returns a concise verdict with top-priority findings.

Whenever possible, agents should check behavior against official schemas, CLIs, or validators rather than relying solely on documentation.

## Step 4: Consolidate findings into CHECKLIST.md

Synthesize all reports into `CHECKLIST.md`:
- **Tier 1**: Up to 10 top-priority fixes for the first PR (ordered by real-world impact and fix simplicity).
- **Tier 2 / Tier 3**: Follow-up fixes and future improvements.
- **Rule summary table**: Clear status for each reviewed rule.
- Include file paths and line numbers for all reported issues.

## Step 5: Independent verification & review

Run a dedicated reviewer subagent to double-check the checklist:
- Reproduce Tier 1 issues on sample repositories or fixtures.
- Verify that proposed fixes don't introduce unintended false negatives.
- Refine priorities and confirm the final list of up to 10 fixes for the initial PR (see [critic](references/critic.md)).

## Step 6: Ship in batches

Bring `main` up to date with upstream first (`git remote -v` names `stbenjam/skillsaw`; fetch it and merge its `main`), then branch from it and implement each fix in its own clear, well-tested commit:
1. Run `make test`, `make lint`, and `make update` (commit any generated changes).
2. When the batch touches a content rule, the lint tree, or `utils.py` read paths, save a benchmark on `main` with `make benchmark-save` and run `make benchmark-compare` on the branch; violation counts cannot show a runtime regression.
3. Run a smoke test on `openshift-eng/ai-helpers`.
4. Compare before-and-after violation counts on sample corpus repositories.
5. Open the PR with clear evidence for each fix, and follow standard post-PR checks.

## Step 7: Final release notes check

Before creating the release tag, verify that release notes clearly highlight all user-visible changes (such as new rules, updated severity defaults, or CLI improvements).
