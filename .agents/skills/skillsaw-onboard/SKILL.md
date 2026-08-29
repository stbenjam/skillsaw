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

## Router

Make each decision only when reached. Read only the selected reference, return
here afterward, and never preload unselected references. Carry forward the
command prefix, violation counts, user choices, and changed-file list.

1. If no working skillsaw command is known, read [install](references/01-install.md).
2. To establish the repository state, read [initial scan](references/02-initial-scan.md).
3. If safe fixes are available, ask permission; if accepted, read [autofix](references/03-autofix.md).
4. If violations remain, ask whether to edit them; if accepted, read [manual fixes](references/04-manual-fixes.md).
5. If accepted violations remain, ask whether to baseline them; if accepted, read [baseline](references/05-baseline.md).
6. Ask whether to create missing configuration; if accepted, read [configuration](references/06-configuration.md).
7. Ask whether to set up skillsaw CI; if accepted, read [CI](references/07-ci.md).
8. Ask separately whether to schedule external link checks; if accepted, read [external links](references/08-external-links.md).
9. Ask whether to add local lint targets; if accepted, read [Makefile](references/09-makefile.md).
10. Ask whether to add a grade badge; if accepted, read [badge](references/10-badge.md).
11. After the selected changes, always read [verification](references/11-verify.md).
