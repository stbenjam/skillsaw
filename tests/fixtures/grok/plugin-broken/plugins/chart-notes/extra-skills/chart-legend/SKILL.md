---
name: chart-legend
description: Build the legend for a harbour approach chart from the layers it draws. Use when a chart gains or loses a layer.
---

# Chart legend

Rebuild a chart's legend so it names every layer the chart actually draws.

## Steps

1. List the layers in the chart source under `charts/`.
2. Read the current legend block at the foot of the chart.
3. Report each layer with no legend entry, and each entry with no layer.

Keep the legend order the same as the draw order; a legend that reorders
the layers reads as a different chart.
