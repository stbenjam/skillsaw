---
name: deeper
description: Nested entry that the fixed one-level Agent Plugins skill scan must never surface. Use when verifying discovery depth.
---

# Deeper

This nested skill sits below the immediate skills/* level, so a conforming
Agent Plugins client never loads it.

## Steps

1. Confirm the discovery layer skipped this file.
2. Report a failure if it ever appears in lint output.
