---
name: Cloud Test Specialist
description: Improves automated test coverage without changing production behavior
target: github-copilot
tools: read, search, edit, test-runner/execute
model: gpt-5.2-codex
disable-model-invocation: false
user-invocable: true
metadata:
  owner: quality-engineering
mcp-servers:
  test-results:
    type: local
    command: node
    args: [scripts/test-results-server.js]
    tools: ["*"]
    env:
      API_KEY: ${{ secrets.TEST_RESULTS_API_KEY }}
---

Analyze the current test suite and add focused regression coverage.
