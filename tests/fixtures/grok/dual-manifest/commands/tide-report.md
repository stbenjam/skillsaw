---
description: Summarize this week's tide windows for a NOAA station
argument-hint: <station-id>
---

# Tide report

Produce the week's survey windows for station `$1`.

1. Read the predictions for the next seven days.
2. Keep the windows at least 90 minutes long below the survey threshold.
3. Write the result as a table of date, start, end, and minimum height.

Say which timezone the times are in. If the station id is unknown, ask for
it rather than guessing a nearby one.
