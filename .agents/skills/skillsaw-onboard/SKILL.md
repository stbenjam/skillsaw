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

Onboard this repo to **skillsaw**, a linter for agentic
contextual building blocks (CLAUDE.md, skills, plugins, agents, hooks, etc.).

Complete the steps in order and report progress after each one. Read only the
current step's reference; do not preload later references. Carry forward the
chosen command prefix, violation counts, user choices, and changed-file list.
When a step directs you to skip ahead, continue at the named step.

1. [Install skillsaw](references/01-install.md)
2. [Run the initial scan](references/02-initial-scan.md)
3. [Run deterministic autofixes](references/03-autofix.md)
4. [Fix remaining violations](references/04-manual-fixes.md)
5. [Baseline accepted violations](references/05-baseline.md)
6. [Create configuration](references/06-configuration.md)
7. [Set up CI](references/07-ci.md)
8. [Add Makefile targets](references/08-makefile.md)
9. [Add a README badge](references/09-badge.md)
10. [Run final verification](references/10-verify.md)
