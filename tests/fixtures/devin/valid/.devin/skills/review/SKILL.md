---
name: review
description: Review the current changes before they are committed. Use when asked to review a diff.
argument-hint: "[path]"
model: sonnet
subagent: false
agent: reviewer
allowed-tools:
  - read
  - grep
permissions:
  allow:
    - Read(src/**)
  deny:
    - exec
  ask:
    - Write(**)
triggers:
  - user
  - model
future-option: accepted
---

# Review Changes

Inspect the selected files and report actionable findings by severity.
