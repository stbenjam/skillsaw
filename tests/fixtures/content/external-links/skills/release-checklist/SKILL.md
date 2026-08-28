---
name: release-checklist
description: Walk the payments settlement release checklist before a nightly deploy. Use when cutting a settlement release or verifying a batch before sign-off.
---

# Release checklist

Work through every step. Stop and escalate in `#payments-releases` if any
step fails — do not deploy a settlement change on a red checklist.

## Before the train

1. Confirm the batch from the previous night balanced to zero.
2. Re-read the [reconciliation runbook](http://127.0.0.1:__PORT__/missing)
   so the rollback path is fresh.
3. Check the [partner status page](http://127.0.0.1:__PORT__/forbidden) for
   acquirer incidents.

## After the deploy

1. Watch the 02:00 UTC batch through to completion.
2. Compare the settlement total against the
   [ledger invariants](http://127.0.0.1:__PORT__/ok).
3. Record the batch id in the release ticket.

Stop once the batch has balanced and the id is recorded.
