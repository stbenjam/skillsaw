# acme-platform

acme-platform is the internal deploy control plane. Issue tracking lives in
Jira and code review lives on GitHub, both reached through MCP servers.

## Looking up work items

<!-- skillsaw-assert content-mcp-tool-name -->
Before you start a change, run mcp__plugin_jira_atlassian__searchJiraIssuesUsingJql
with a JQL filter scoped to the current sprint, so you do not duplicate work
someone has already picked up.

<!-- skillsaw-assert content-mcp-tool-name -->
Read the ticket body with `mcp__plugin_jira_atlassian__getJiraIssue` and quote
the acceptance criteria in your plan before writing any code.

## Reading files from GitHub

<!-- skillsaw-assert content-mcp-tool-name -->
Fetch file contents with `mcp__plugin_github_github__get_file_contents` rather
than a raw HTTP request — the MCP call carries authentication for private
repositories and returns the ref you asked for.

Use `list_commits` when you need the history of a single file; it takes the
same owner, repo, and path arguments.

## Enabling the servers

Grant the tools in `.claude/settings.json`. Configuration needs the
fully-qualified identifier, so the entries below are correct as written:

```json
{
  "permissions": {
    "allow": [
      "mcp__plugin_jira_atlassian__searchJiraIssuesUsingJql",
      "mcp__plugin_github_github__get_file_contents"
    ]
  }
}
```

A server with no tool segment, written as mcp__atlassian on its own, names
the server rather than a tool and needs no rewrite.
