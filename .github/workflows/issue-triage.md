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
#   - Egress is pinned to GitHub + OpenRouter.
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
    - defaults                      # GitHub, package registries
    - openrouter.ai                 # model API egress

# Run GLM 5.2 through OpenRouter via Copilot BYOK. These COPILOT_PROVIDER_*
# vars are the ONLY secret-carrying engine.env keys gh-aw strict mode allows —
# the provider key is handed to the model layer, not exposed to the agent
# container, so a compromised agent cannot read or exfiltrate it.
engine:
  id: copilot
  env:
    COPILOT_PROVIDER_BASE_URL: https://openrouter.ai/api/v1
    COPILOT_PROVIDER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
    COPILOT_MODEL: z-ai/glm-5.2

safe-outputs:
  add-comment:                      # posted by the privileged safe-output job
  threat-detection: true            # scan agent output before posting (default when safe-outputs is set)
---

# skillsaw Issue Triage

A maintainer has labeled the triggering issue `triage-for-agent`. Triage that
issue using the **skillsaw-issue-triage** skill, and post the triage comment it
produces.
