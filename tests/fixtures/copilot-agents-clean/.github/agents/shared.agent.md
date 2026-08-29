---
name: Shared Reviewer
description: Reviews changes for correctness across local and cloud Copilot environments
tools: [read, search, example-extension/unknown-tool]
model: [Claude Sonnet 4.5, GPT-5.2]
mcp-servers:
  repository-search:
    type: stdio
    command: node
    args: [scripts/search-server.js]
---

Review the requested changes and report concrete correctness risks.
