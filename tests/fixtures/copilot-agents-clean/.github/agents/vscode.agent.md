---
name: Workflow Planner
description: Produces an implementation plan and hands approved work to an implementation agent
target: vscode
argument-hint: Describe the feature or refactoring to plan
tools: [read, search, agent]
agents: [Researcher, Implementer]
model: [Claude Sonnet 4.5, GPT-5.2]
handoffs:
  - label: Start Implementation
    agent: Implementer
    prompt: Implement the approved plan from this conversation.
    send: false
    model: GPT-5.2 (copilot)
hooks:
  PostToolUse:
    - type: command
      command: ./scripts/format-changed-files.sh
---

Create a detailed plan, ask for approval, and offer the implementation handoff.
