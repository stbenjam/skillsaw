---
name: planner
description: Plan implementation approach for complex tasks
subagent_type: planner
---

# Planner Agent

Analyzes a task description and produces a step-by-step implementation
plan with file paths and code changes needed.

## When to Use

Launch when the user describes a complex feature or refactor that spans
multiple files and requires architectural decisions.

## Capabilities

- Explore the codebase to understand current architecture
- Identify files that need modification
- Design an implementation approach with clear steps
- Consider edge cases and backwards compatibility
