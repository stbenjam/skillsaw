---
description: Stage and commit the working tree with a conventional message
subtask: true
---

Read the staged diff with `git diff --cached`.

Write a conventional-commits subject line under 72 characters: a type
(`feat`, `fix`, `chore`, `docs`, `test`), an optional scope in parentheses,
then the change in the imperative mood.

Add a body only when the subject cannot carry the reason. Reference the
issue key on its own trailer line, e.g. `Refs: LED-88`.

Commit with the message you wrote. Stop there — do not push.
