---
name: tide-window
description: Find the low-tide windows long enough for a shoreline survey on a given date and station. Use when planning field work against NOAA tide predictions.
---

# Tide window

Use this skill when someone needs to know when a stretch of shoreline is
walkable, not when they want the raw predictions.

## Steps

1. Ask for the NOAA station id and the date range if either is missing.
2. Fetch the predictions covering that range.
3. Keep every window where the predicted height stays below the survey
   threshold for at least 90 minutes.
4. Report each window as a start time, an end time, and the minimum height
   inside it.

Report the station's timezone with every time.
