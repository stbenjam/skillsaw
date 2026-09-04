---
description: Render one tile and report its size and feature count
---

# Tile check

Render the tile named in the request and report what came back.

1. Run `cargo run --bin tessellate -- render --z $Z --x $X --y $Y`.
2. Read the size and feature count from the command's output.
3. Compare both against `docs/tile-budgets.md`.

Report the tile, its size, its feature count, and whether each is inside
the documented budget.
