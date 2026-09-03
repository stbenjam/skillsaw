---
name: triage-pager
description: Pager triage for the platform team.
---

# Triage Pager

Turns a page into either a resolved incident or a handoff carrying enough
context for the next responder.

## First five minutes

- Acknowledge the page.
- Read the alert's runbook link. Every alert defined in
  [alerts.yaml](config/alerts.yaml) carries one.
- Post a one-line status in the incident channel.

## Deciding severity

Severity comes from customer impact, not from how loud the alert is. The
matrix is in [the severity guide](docs/severity-matrix.md).

Hand off with a written summary at the end of your shift, following
[the handoff format](docs/handoff.md).
