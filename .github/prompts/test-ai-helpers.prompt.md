---
description: Test skillsaw against the ai-helpers marketplace repo
---

# Test Against ai-helpers

The openshift-eng/ai-helpers repo is the primary integration test target. Any
change to skillsaw must pass clean against it.

## Steps

1. Clone: `git clone https://github.com/openshift-eng/ai-helpers.git /tmp/ai-helpers`
2. Install skillsaw locally: `pip install -e .`
3. Run: `skillsaw /tmp/ai-helpers`
4. Expected: exit code 0 (no errors)

## Notes

- ai-helpers uses `.claudelint.yaml` (the old config name) — skillsaw discovers it via fallback
- ai-helpers disables agentskills rules in its config because its skills predate the spec
- If ai-helpers ever updates their skills, the agentskills disables can be removed from their config and from our CI
- Never ship a change that causes `skillsaw /tmp/ai-helpers` to exit non-zero
