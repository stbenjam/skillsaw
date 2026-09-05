---
description: Reviews changes with platform-specific status hooks
target: vscode
hooks:
  PostToolUse:
    - type: command
      bash: printf shell-ready
      powershell: Write-Output shell-ready
      args: [ignored-extra-argument]
      async: [installer-metadata]
---

Review the proposed changes for correctness and maintainability. Summarize
concrete findings with their locations and explain the effect on users.
