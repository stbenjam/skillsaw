# kiro-mcp-valid

Check Kiro workspace `.kiro/settings/mcp.json` and agent `mcpServers` field types.
This rule is opt-in. Shared MCP credential and prohibition checks also read these
servers, independently of this rule's setting.

## How to fix

Place server objects under `mcpServers`. Use strings for commands and URLs,
string arrays for arguments and tool-name lists, string maps for environment
variables and headers, and a boolean for `disabled`.

Partial server overrides are accepted. The rule does not require every record to
supply a command or URL, select a transport, or validate OAuth negotiation,
permissions or live server behavior. See the [Kiro support boundaries](../kiro.md).
