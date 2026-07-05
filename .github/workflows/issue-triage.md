---
# skillsaw issue triage (GitHub Agentic Workflow — requires `gh aw compile`)
#
# Security model (see THREAT_MODEL.md and the gh-aw threat-detection reference):
#   - Trust gate: only fires when a maintainer applies the `triage-for-agent`
#     label (labeled event + names filter + roles gate). Anonymous/attacker
#     issues never auto-trigger the agent.
#   - Powerless agent: `permissions: read-all` — the agent that reads the
#     untrusted issue text cannot write anything.
#   - Privilege separation: the triage comment is posted by the `safe-outputs`
#     job, not the agent. `threat-detection` (auto-enabled by safe-outputs)
#     scans the proposed comment for prompt_injection / secret_leak before it
#     is posted, fail-closed.
#   - Egress is pinned to GitHub (+ the Copilot model API).
on:
  issues:
    types: [labeled]
    names: [triage-for-agent]      # only this maintainer-applied label
  roles: [admin, maintainer, write] # only a trusted actor's label fires it
  reaction: "eyes"                  # bot 👀s the issue when it picks it up

permissions: read-all               # powerless agent — no write scope

timeout-minutes: 10

network:
  allowed:
    - defaults                      # GitHub + Copilot model API

# Copilot engine pinned to Opus 4.8, using Copilot's hosted model directly.
# No BYOK / provider key — there is no model-provider secret to manage or leak.
engine:
  id: copilot
  model: claude-opus-4.8

safe-outputs:
  add-comment:                      # posted by the privileged safe-output job
  remove-labels:                    # clear the trigger label once triage is done
    allowed: [triage-for-agent]
    max: 1
  threat-detection: true            # scan agent output before posting (default when safe-outputs is set)
---

# skillsaw Issue Triage

A maintainer has labeled the triggering issue `triage-for-agent`. Triage that
issue using the **skillsaw-issue-triage** skill, and post the triage comment it
produces. Once the comment is posted, remove the `triage-for-agent` label.
