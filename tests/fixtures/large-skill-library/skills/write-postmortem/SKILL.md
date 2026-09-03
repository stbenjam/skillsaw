---
name: write-postmortem
description: Postmortem authoring for production incidents.
---

# Write Postmortem

Produces a blameless postmortem within five working days of an incident
being resolved.

## Structure

- A timeline in UTC, from first signal to all-clear.
- Contributing factors, each with evidence.
- Action items with an owner and a date.

Pull the timeline from the incident channel export and the alert history.
[The export tool](tools/incident-export.md) writes both into one file.

Follow the wording conventions in [the style
guide](docs/postmortem-style.md); reviewers reject drafts that name
individuals.
