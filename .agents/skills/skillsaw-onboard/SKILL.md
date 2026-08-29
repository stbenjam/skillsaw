---
name: skillsaw-onboard
description: "Onboard a repository to skillsaw — run the linter, apply autofixes, manually fix remaining violations, set up CI, and create a baseline. Use when adopting skillsaw on a new or existing project."
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

Replace brace-delimited fields below with facts from the repository or scan;
never show placeholders to the user, and render singular or plural wording
naturally.

### 1. Establish the current state

If no working skillsaw command is known, read
[install](references/01-install.md). Then read
[initial scan](references/02-initial-scan.md) and report its violations before
offering changes.

### 2. Apply safe fixes

If the scan identifies safe deterministic fixes, ask:

> The scan found safe deterministic fixes for {count} violations. Applying them
> will edit the affected context files; I will show the changes and lint again
> afterward. Should I apply those fixes now?

If yes, read [autofix](references/03-autofix.md). If no, preserve the count.

### 3. Make judgment-based fixes

If violations remain, ask:

> {count} violations remain and need judgment rather than a mechanical fix. I
> can inspect each affected file, consult the rule guidance, make targeted
> wording or structure changes, and lint again. Should I fix them now?

If yes, read [manual fixes](references/04-manual-fixes.md). If no, preserve the
violations for the baseline decision.

### 4. Baseline accepted violations

If reviewed violations remain, ask:

> {count} reviewed violations remain. A baseline records them in
> `.skillsaw-baseline.json` as accepted debt so CI fails only on new
> violations; it does not fix them, and the file can shrink as they are fixed.
> Should I create or update that baseline?

If yes, read [baseline](references/05-baseline.md).

### 5. Add configuration

If `.skillsaw.yaml` is missing, ask:

> This repository has no `.skillsaw.yaml`. I can add the default tracked
> configuration so rule settings and exclusions have an explicit place; lint
> behavior remains at the defaults until it is customized. Should I create it?

If yes, read [configuration](references/06-configuration.md).

### 6. Add skillsaw CI

Ask:

> I can add skillsaw to {detected CI system or "your CI"} so future changes are
> linted automatically. GitHub uses a pinned, read-only lint workflow; optional
> PR comments use a separate write-enabled workflow. GitLab gets a Code Quality
> job. Should I set this up? If yes, which CI system?

If yes, read [CI](references/07-ci.md), using the named CI system.

### 7. Add external link checking

If GitHub Actions is available, ask separately:

> External links decay over time and need recurring audits, but checking them
> during every skillsaw lint would add network access, latency, and failures
> caused by third-party outages. We recommend a dedicated link checker such as
> Lychee for this job. I can add a weekly GitHub Actions workflow that runs
> Lychee on a schedule or manually, outside your pull-request merge gate. This
> adds `.github/workflows/link-check.yml` and a pinned third-party Action to
> maintain. Would you like me to set that up?

If yes, read [external links](references/08-external-links.md).

### 8. Add local commands

Ask:

> I can add version-pinned `lint` and `lint-fix` Makefile targets for repeatable
> local use through uvx or a container, without overwriting existing targets.
> This creates or edits `Makefile`. Should I add them?

If yes, read [Makefile](references/09-makefile.md).

### 9. Add a grade badge

If the repository has a README, ask:

> I can generate `.skillsaw-badge.json` and add a skillsaw grade badge to the
> README. The badge reflects the committed lint result, ignores the baseline,
> and must be regenerated when agent context changes. Should I add it?

If yes, read [badge](references/10-badge.md).

### 10. Verify the result

After all accepted routes finish, always read
[verification](references/11-verify.md).
