---
description: Review configuration changes. Use when checking platform setup.
target: vscode
hooks:
  PreToolUse:
    - type: command
      command: ''
      linux: ''
    - type: command
      command: []
    - type: prompt
      command: printf ready
---
# Configuration review

Read the changed settings and compare each platform override with its default.
Record the expected behavior before approving the configuration update.
