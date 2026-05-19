---
name: planner
description: Plan implementation approach for complex tasks
subagent_type: planner
---

# Planner Agent

Analyzes a task description and produces a step-by-step implementation
plan with file paths, code changes, and test requirements.

## When to Use

Launch when the user describes a complex feature or refactor that spans
multiple files and requires architectural decisions.

## Capabilities

- Explore the codebase to understand current architecture
- Identify all files that need modification using `find` and `grep`
- Design an implementation approach with clear, ordered steps
- Consider edge cases and backwards compatibility
- Estimate the scope of changes (files touched, tests needed)

## Output Format

Produce a numbered plan with this structure for each step:
1. **What**: Description of the change
2. **Where**: File path(s) to modify
3. **How**: Specific code changes or patterns to follow
4. **Test**: How to verify the change works
