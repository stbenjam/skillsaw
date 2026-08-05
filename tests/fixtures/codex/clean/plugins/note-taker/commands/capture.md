---
description: Capture a note from the current conversation into the daily log
---

# Capture

Write the current discussion into today's note file.

## Run the capture

1. Read `notes/$(date +%Y-%m-%d).md`. Create it with an `# Notes` heading
   when it does not exist.
2. Summarize the last exchange in two or three sentences. Keep the user's
   own wording for anything they stated as a decision.
3. Append the summary under a `## <HH:MM>` heading.

## Stop when

The file contains the new entry and nothing else changed. Report the path
you wrote to. Do not reformat entries that were already in the file.
