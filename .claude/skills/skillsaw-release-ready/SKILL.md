---
name: skillsaw-release-ready
description: Audit skillsaw for release readiness — adversarially review every rule added since the last tag against real GitHub content, audit the code by dimension, consolidate an adversarially approved fix list, and ship it in batches of discrete commits. Use before cutting a release.
compatibility: Requires git, gh CLI, internet access, and subagents (Opus for reviewers). Uses ~/tmp for a multi-gigabyte corpus.
license: Apache-2.0
user-invocable: true
metadata:
  author: stbenjam
  version: "1.0"
---

<!-- Source paths below are repo-root-relative references, not links navigable from this skill's directory. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

# skillsaw Release Ready

A release is ready when every rule added since the last tag has survived an
adversarial review against real repositories, every dimension of the code has
been audited, and the fixes an independent critic approved have shipped.
This skill runs that sweep with subagents in parallel and lands the fixes in
batches of ten discrete commits per PR.

Three questions decide every finding's priority, and every reviewer answers
them:

1. Does it affect common usage? Rare edge cases can be suppressed with a
   `skillsaw-disable` directive; JSON has no inline disable.
2. Is it correct? A false positive on content the target tool accepts is the
   worst outcome for a linter.
3. Is it annoying? Would users find the rule overbearing, or firing far too
   often on skills that work?

## Step 1: Establish scope

```bash
git fetch --tags
git diff --name-status v<last>..HEAD -- src/skillsaw/rules/builtin/ | grep '^A'
git log --merges --format=%s v<last>..HEAD
gh pr view <n> --json title,body   # each prior release-readiness PR
```

Record the new rule ids, the rules whose files changed, and the fixes earlier
passes already landed. Reviewers must be told what was already fixed so they
dig for what was missed.

## Step 2: Build the environment

- Scratch lives under `~/tmp/skillsaw-audit/`: `corpus/`, `reports/`,
  `briefs/`, `work/<agent>/`. The system `/tmp` is too small.
- Shallow-clone a corpus of real repositories into `corpus/` before launching
  anything: the reference collections for every ecosystem skillsaw supports,
  the largest marketplaces, and the repositories `gh search code` finds for
  each new rule's file type. Read [corpus](references/corpus.md).
- Install the last release into `~/tmp/skillsaw-audit/venv-<last>/` for
  differential runs. Never `pip install -e` from a worktree into the shared
  `.venv`; that breaks every agent at once.
- `skillsaw lint <path> --rule <id>` force-enables an opt-in or `since`-gated
  rule, so reviewers can exercise any rule directly.

## Step 3: Launch the reviewers and auditors

One Opus subagent per new rule, plus one auditor per dimension of the code, all
in one turn so they run in parallel. Each reads a shared brief, writes its
report to `reports/<name>.md`, and returns a verdict plus its P0 and P1
findings in under 40 lines. Read [briefs](references/briefs.md) for the two
brief templates and the dimension list.

Reviewers use real oracles wherever one exists: the vendor's own validator
(`mcp-publisher validate`), CLI (`devin rules list`), binary (`opencode`),
schema (`opencode.ai/config.json`), or lockfile writer. A reviewer that
reasons from memory of the docs finds nothing the docs already said.

While they run, verify the two or three most surprising claims yourself as
they arrive; a report that says a check fails on `main` too has changed its
own priority.

## Step 4: Consolidate the checklist

Fold every report into `CHECKLIST.md`: a health verdict, Tier 1 (the ten for
the first PR, ordered by common usage times correctness divided by size),
Tier 2 (next PR), Tier 3 (backlog), a per-rule verdict table, and a
"verified fine" list so nobody re-checks it. Cite `file:line` and a corpus
path for every item.

## Step 5: Send the critic

One Opus subagent attacks the checklist: reproduces every Tier 1 item, attacks
each proposed fix for new false negatives and for conflicts with recorded
maintainer decisions, promotes and demotes across tiers, hunts for what the
whole audit missed, and returns an approved Tier 1 of at most ten. Its
verdict, not the checklist, decides what ships first. Read
[critic](references/critic.md).

## Step 6: Ship in batches

Branch from `main`; one item per commit, each with its tests and its doc, in
the critic's order. Before pushing: `make test`, `make lint`, `make update`
(commit the output), a smoke run on `openshift-eng/ai-helpers`, and a
before/after count of every touched rule on ten corpus repositories with the
last release's venv. Open the PR with the evidence per item and the
next-batch list, then follow the post-PR checklist in the development rules.

Push protection scans every commit: build token-shaped test values by
concatenation, and squash a fix into the commit that introduced the literal.

## Step 7: Gate the tag

Before tagging, the release notes must name every user-visible behavior
change the sweep found — discovery reaching new files, a rule's severity
moving, a CLI contract changing — not only the new rules. The critic lists
them; the tag waits for them.
