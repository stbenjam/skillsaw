---
description: Reviews changes with defaulted command hook types
target: vscode
hooks:
  PreToolUse:
    - command: printf direct-ready
  SessionEnd:
    - hooks:
        - bash: printf nested-ready
  ErrorOccurred:
    - type: command
      command: printf error-recorded
---

Review the proposed changes for correctness and maintainability. Summarize
concrete findings with their locations and explain the effect on users.
