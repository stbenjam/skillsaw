---
description: 2026-09-04
argument-hint: yes
model: 42
subagent: false
allowed-tools: [Read, 42, false, null]
permissions:
  allow: [Read(src/**), 42, null]
  deny: [false]
  ask: [yes]
---
# Review local metadata

Read the selected metadata and record its current values.
Compare each changed field with the documented behavior for its consumer.
