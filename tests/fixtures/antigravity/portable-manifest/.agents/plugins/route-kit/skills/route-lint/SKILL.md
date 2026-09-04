---
name: route-lint
description: Use when a route definition fails validation, to find which stop sequence broke the shape and what the last valid sequence was.
---

# Route lint

Explain why one route definition failed validation.

## Steps

1. Run `./bin/routeboard route lint --route "$ROUTE_ID"`.
2. Read the failing stop sequence from the command's output.
3. Compare it against the last accepted sequence in `data/routes.json`.

Report the failing stop, the rule it broke, and the last sequence that
passed.
