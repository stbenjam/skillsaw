# Workflows

Most workflows here are ordinary GitHub Actions YAML. One is different:

## `issue-triage` — agentic issue triage (GitHub Agentic Workflows / gh-aw)

`issue-triage.md` is a [gh-aw](https://github.github.com/gh-aw/) workflow: a
markdown file with YAML frontmatter (the agent's prompt is the body). It is
**compiled** to the runnable `issue-triage.lock.yml` — that generated file is
what GitHub Actions executes.

**What it does.** When a maintainer applies the `triage-for-agent` label to an
issue, an agent classifies it (bug / feature / documentation / question /
other), assesses the claim against the code by reading only, enriches it with
the likely rule + `file:line`, related issues, and suggested labels, and posts
one advisory triage comment.

### Operating it

- **Trust gate.** It runs **only** on the `labeled` event for `triage-for-agent`,
  and only when the actor has `write`/`maintain`/`admin` (`roles:`). Anonymous
  or attacker-authored issues never auto-trigger it — a human opts each issue in.
  Create the label once: `gh label create triage-for-agent --color a371f7 --description "Approved for agent to triage"`.
- **Model.** GLM 5.2 via OpenRouter, using the Copilot engine's BYOK mode. The
  only secret is `OPENROUTER_API_KEY` (repo secret). gh-aw excludes the provider
  key from the agent container, so the agent cannot read or exfiltrate it.
- **Security posture.** Read-only agent (`permissions: read-all`), egress pinned
  to GitHub + OpenRouter, comment posted by a separate privileged `safe-outputs`
  job, and gh-aw threat-detection scans the proposed comment for prompt injection
  / secret leaks before it is posted (fail-closed).

### Regenerating after an edit

Editing `issue-triage.md` requires recompiling; never hand-edit the `.lock.yml`.

```bash
gh extension install githubnext/gh-aw   # once
gh aw compile issue-triage              # regenerates issue-triage.lock.yml
```

Commit both `issue-triage.md` and `issue-triage.lock.yml` together. If the
compile reports a new secret or action, review it and note it in the PR (gh-aw's
supply-chain guard); pass `--approve` once reviewed.
