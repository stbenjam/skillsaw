---
description: Review APIs. Use when verifying protocol changes.
tools: read
resources:
  - file://docs/missing.md
mcpServers:
  bad:
    command: 42
    args: [valid, 42]
  secret:
    url: https://mcp.example.com
    headers:
      Authorization: Bearer ghp_1234567890abcdefghijklmnopqrstuvwxyz
---
# Review requests

You might want to inspect validation.
Read [the request contract](missing.md) before editing handlers.
