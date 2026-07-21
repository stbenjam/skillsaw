---
name: skillsaw-issue-triage
description: Triage a GitHub issue filed against skillsaw — classify it (bug, feature, docs, question, other), verify its claims against the codebase, enrich it with missing details, and post one structured triage comment. Use to triage and label incoming issues, not to fix them.
compatibility: Requires git, gh CLI, and internet access
user-invocable: true
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Issue Triage

Triage a single open issue on the **skillsaw** linter. Check what kind of
issue it is, check whether its claims hold up against the actual code, fill in
the details it is missing, review the evidence, and leave one triage
comment. This skill **triages** issues — never fix them here (that job belongs to `skillsaw-issue-solver`).

Read the detailed evaluation checklist for each classification in `references/`,
and read **only** the checklist for the class the issue falls into (progressive disclosure).
Keep this file lean and pull the checklist in on demand.

## Step 1 — Read the Issue

Run this for the issue number you were given:

```bash
gh issue view <number> --json number,title,body,labels,author,comments,createdAt
```

Read the title, body, and every comment before judging anything. Note the
skillsaw version the reporter names (or none), and check any config, command, or file content they pasted.

## Step 2 — Classify

Set exactly one primary class. When an issue spans two, pick the one that determines the next action and note the secondary in the comment.

| Class | The issue is… | Evaluation checklist |
|---|---|---|
| `bug` | A claim that skillsaw behaves incorrectly — wrong violation, crash, false positive/negative, bad autofix | [`references/bug-evaluation.md`](references/bug-evaluation.md) |
| `feature` | A request for new behavior — a new rule, flag, config option, output format, or tool/format support | [`references/feature-evaluation.md`](references/feature-evaluation.md) |
| `documentation` | Docs are missing, wrong, or unclear (README, skillsaw.org, rule docs) — code behavior is not disputed | [`references/other-evaluation.md`](references/other-evaluation.md) |
| `question` | A usage/support question, not a defect or request | [`references/other-evaluation.md`](references/other-evaluation.md) |
| `other` | Duplicate, invalid, spam, out-of-scope, or needs-more-info | [`references/other-evaluation.md`](references/other-evaluation.md) |

Write the class and a one-sentence rationale.

## Step 3 — Verify Accuracy

**Read the checklist for the chosen class now** (`references/*.md`) and work it.
Check whether the issue is *accurate* — do its claims match how skillsaw actually behaves?

- For a **bug**: run the repro against the current code. Trace the cited behavior
  to the responsible rule or `src/` module, then verify it. A bug you cannot
  reproduce, or that describes intended behavior, is not confirmed — always say so.
- For a **feature**: check whether it already exists, whether it fits skillsaw's
  scope (core vs a rule plugin), and verify it would not break existing users.
- For **documentation / question / other**: verify the underlying facts before agreeing or redirecting.

Cite what you checked with `file:line` references and command output — never assert a conclusion you did not verify.

## Step 4 — Enrich

Add the details the issue is missing so it is actionable without a round-trip:

- **Reproduction**: write a minimal repro (config + input file + command + observed vs expected) when the reporter left one out and you can construct one.
- **Locus**: include the rule ID, file, and line most relevant to the issue.
- **Version / environment**: include the version the behavior was verified against, and whether it still reproduces on `main`.
- **Related work**: review duplicate or related issues and any open PR that already touches this (`gh issue list` / `gh pr list --search`).
- **Suggested labels**: include labels (e.g. `bug`, `enhancement`, `documentation`, `question`, `duplicate`, `needs-info`, `good-first-issue`), but never apply them unless asked.

## Step 5 — Decide the Recommendation

Set exactly one recommendation — this is the headline of the triage comment:

| Recommendation | When |
|---|---|
| 🛠️ **FIX — REPRODUCED** | A real defect you reproduced or confirmed against the code (a genuinely wrong or missing doc counts here too). |
| ✨ **IMPLEMENT — GOOD IDEA** | An in-scope feature worth building into skillsaw core. |
| 🔌 **PLUGIN** | In skillsaw's domain but niche / single-vendor — belongs in a rule plugin, not core. Link `skillsaw.org/plugins/`. |
| ⛔ **REJECT** | Out of scope, not reproduced, works-as-intended, invalid, duplicate, or answered. |

Follow the class checklist to decide: a bug that reproduces → FIX,
one that doesn't → REJECT; for a feature, follow the domain gate in
[`references/feature-evaluation.md`](references/feature-evaluation.md) (out of domain → REJECT, niche → PLUGIN,
broadly useful → IMPLEMENT).

## Step 6 — Post One Triage Comment

Read [`references/triage-template.md`](references/triage-template.md), then post it as exactly ONE comment:

```bash
gh issue comment <number> --body "$(cat <<'TRIAGE'
<rendered triage>
TRIAGE
)"
```

This skill is advisory: keep its output a recommendation for a maintainer. Post
the triage comment on your own initiative, but never close, reassign, or label
the issue yourself — always leave that to a human. Follow one exception only: a
label action the invoking context directs — for instance, keep clearing an
automation's own trigger label once you post the comment. Always carry that out.
