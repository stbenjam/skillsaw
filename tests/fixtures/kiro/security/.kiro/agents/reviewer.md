---
name: reviewer
description: Review API changes. Use when changing request handlers.
mcpServers:
  internal-docs:
    url: https://mcp.example.com/docs
    oauth:
      clientId: review-client
      clientSecret: zQ7mJ9vP2rT4nL6xD8bH5cW3sF1k
  placeholder-docs:
    url: https://mcp.example.com/docs
    oauth:
      clientSecret: ${DOCS_CLIENT_SECRET}
---
# Review API changes

Inspect request validation and report reproducible failures with their inputs.
