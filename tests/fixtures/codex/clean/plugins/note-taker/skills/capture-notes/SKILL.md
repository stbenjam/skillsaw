---
name: capture-notes
description: Turn raw meeting notes into a structured summary with owners and due dates. Use when documenting a meeting.
---

# Capture Notes

Use this skill when the user pastes raw meeting notes and wants them organized.

## Steps

1. Read the notes and identify every decision, action item, and open question.
2. Assign each action item an owner. If the notes name no owner, mark it `UNASSIGNED`.
3. Emit a markdown summary with three sections: Decisions, Action Items, Open Questions.

Stop once the summary is written. Do not create tickets unless the user asks.
