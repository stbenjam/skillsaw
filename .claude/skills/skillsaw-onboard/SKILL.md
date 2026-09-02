---
name: skillsaw-onboard
description: "Onboard a repository to skillsaw — run the linter, triage the findings by rule, apply autofixes, manually fix what remains, set up CI, and create a baseline. Use when adopting skillsaw on a new or existing project."
compatibility: "Requires skillsaw (uvx skillsaw or pip install skillsaw). Optional: gh CLI for GitHub Actions setup."
license: Apache-2.0
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Onboard

Onboard this repository to **skillsaw**, a linter for agentic
contextual building blocks (CLAUDE.md, skills, plugins, agents, hooks, etc.).

## Workflow

Ask one routing question at a time and wait for the answer. An explicit choice
in the user's request already counts as an answer. Read a reference only after
its condition or a yes answer routes to it; do not read the reference to
formulate the question. After completing it, return here. If the answer is no,
continue to the next checkpoint without reading it. Carry forward the command
prefix, counts, choices, and changed-file list.

Resolve every `references/...` path relative to the directory containing this
`SKILL.md`, never relative to the target repository or the process's current
working directory. If this file was fetched from the web, resolve each
reference against the parent URL of this file and fetch it from that sibling
location.

Replace brace-delimited fields below with facts from the repository or scan;
never show placeholders to the user, and render singular or plural wording
naturally.

### 1. Establish the current state

If no working skillsaw command is known, read
[install](references/01-install.md). Then read
[initial scan](references/02-initial-scan.md) and report its violations before
offering changes.

### 2. Triage findings by rule

Run `skillsaw lint --format json -v` to see all violations, including the info-level ones the first scan hid. Group the results by `rule_id` and sort them by count. Sample 3–5 examples from any large cluster (e.g. >10% of total findings or >20 issues) to understand the root cause before deciding on an action.

Follow [triage](references/12-triage.md) to categorize each group into **Fix now**, **Baseline**, or **Configure**, and present a clear summary table to the user for confirmation before making changes. Carry the agreed buckets into the subsequent steps.

### 3. Apply autofixes

If the **Fix now** bucket holds autofixable findings, ask:

> The plan includes autofixes for {count} violations: {safe count} safe and
> {suggest count} suggested. Applying them will edit the affected context
> files; I will show the changes and lint again afterward. Should I apply
> those fixes now?

If yes, read [autofix](references/03-autofix.md). If no, preserve the count.

### 4. Make judgment-based fixes

If violations remain, offer manual fixes and a baseline as alternatives. A
baseline is especially useful when hundreds of findings would otherwise block
adoption or the user wants to move forward from a clean starting point. Ask:

> {count} violations remain and need judgment rather than a mechanical fix. I
> can inspect and fix them now, or review them as accepted existing debt and
> baseline them in step 6 so onboarding can move forward while CI catches
> new findings. Which path would you prefer?

If the user chooses fixes, read [manual fixes](references/04-manual-fixes.md).
If the user chooses a baseline, review the remaining findings by rule, severity,
and affected paths. The baseline command records every eligible finding that
remains, so fix, suppress, or otherwise remove anything the user does not
accept before continuing; pause onboarding if that cannot be done safely. Then
preserve the accepted remaining set for the baseline decision. Do not require
accepted findings to be fixed first.

### 5. Add or update configuration

If the triage plan placed any rule in **Configure**, read
[configuration](references/06-configuration.md) without asking again; the
user confirmed those settings in step 2. Otherwise, if `.skillsaw.yaml` is
missing, ask:

> This repository has no `.skillsaw.yaml`. I can add the default tracked
> configuration so rule settings and exclusions have an explicit place; lint
> behavior remains at the defaults until it is customized. Should I create it?

If yes, read [configuration](references/06-configuration.md).

### 6. Baseline accepted violations

If reviewed violations remain, ask:

> {count} reviewed violations remain. A baseline records them in
> `.skillsaw-baseline.json` as accepted debt so CI fails only on new
> violations; it does not fix them, and the file can shrink as they are fixed.
> Should I create or update that baseline?

If yes, read [baseline](references/05-baseline.md).

### 7. Add skillsaw CI

Ask:

> I can add skillsaw to {detected CI system or "your CI"} so future changes are
> linted automatically. GitHub uses a pinned, read-only lint workflow; optional
> PR comments use a separate write-enabled workflow. GitLab gets a Code Quality
> job. Should I set this up? If yes, which CI system?

If yes, read [CI](references/07-ci.md), using the named CI system.

### 8. Add external link checking

If GitHub Actions is available, ask separately:

> External links decay over time and need recurring audits, but checking them
> during every skillsaw lint would add network access, latency, and failures
> caused by third-party outages. We recommend a dedicated link checker such as
> Lychee for this job. I can add a weekly GitHub Actions workflow that runs
> Lychee on a schedule or manually, outside your pull-request merge gate. This
> adds `.github/workflows/link-check.yml` and a pinned third-party Action to
> maintain. Would you like me to set that up?

If yes, read [external links](references/08-external-links.md).

### 9. Add local commands

Ask:

> I can add version-pinned `lint` and `lint-fix` Makefile targets for repeatable
> local use through uvx or a container, without overwriting existing targets.
> This creates or edits `Makefile`. Should I add them?

If yes, read [Makefile](references/09-makefile.md).

### 10. Add a grade badge

If the repository has a README, ask:

> I can generate `.skillsaw-badge.json` and add a skillsaw grade badge to the
> README. The badge reflects the committed lint result, ignores the baseline,
> and must be regenerated when agent context changes. Should I add it?

If yes, read [badge](references/10-badge.md).

### 11. Verify the result

After all accepted routes finish, always read
[verification](references/11-verify.md).
