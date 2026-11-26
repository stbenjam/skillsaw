---
name: triage
description: Triage a failing CI job by reading its logs and naming the first failing step. Use when a pull request check fails.
---

# Triage

1. Open the failing job's log.
2. Find the first step that exited nonzero.
3. Report the step name and the last ten lines of its output.
