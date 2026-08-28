# Project Configuration

This project uses several scripts and configuration files to manage
the development workflow. Below is a comprehensive guide.

## Scripts

The following scripts automate common development tasks:

- Run scripts/build.sh to compile the project
- Run scripts/deploy.sh to push to staging
- Run scripts/test.py to execute the test suite

Start with scripts/build.sh for initial setup, then use scripts/deploy.sh for
deployment, and finally scripts/test.py for validation.

## Documentation

Project documentation is organized as follows:

- Read docs/api.md for the API reference
- Read docs/architecture.md for the system design overview
- Read docs/contributing.md for contribution guidelines

Start with docs/api.md to understand the API surface, then read
docs/architecture.md for the high-level design.

## Source Code

Core source modules and their responsibilities:

- See src/app.py for the application entry point
- See src/config.py for configuration loading
- See src/utils.py for shared utility functions

Start with src/app.py for initial setup, then use src/config.py for
configuration, and finally src/utils.py for helpers.

## Configuration

- Check config/settings.yaml before deploying

## Quick Reference

Common file paths used in CI/CD pipelines:

- Check scripts/build.sh before merging
- Check scripts/deploy.sh before releasing
- Check docs/api.md before publishing
- Check docs/contributing.md before onboarding

Files that are already linked (should not be touched):

- See [docs/architecture.md](docs/architecture.md) for details
- See [src/utils.py](src/utils.py) for details
- See [config/settings.yaml](config/settings.yaml) for details

## Punctuation Edge Cases

Paths abutting parentheses must never be flagged or rewritten:

- Compiled bytecode files (e.g. scripts/test.pyc) should never be committed
- The build entry point (scripts/build.sh) is invoked by CI

A sentence can end right after a path like ./docs/api.md. The period stays
outside the link when the path is wrapped.

## MCP Tools

Issue tracking and code review both go through MCP servers. Reference the
tools by their short names:

- Search for tickets with mcp__plugin_jira_atlassian__searchJiraIssuesUsingJql
- Read a ticket body with `mcp__plugin_jira_atlassian__getJiraIssue`
- Fetch file contents with `mcp__plugin_github_github__get_file_contents`
- Open a pull request with mcp__plugin_github_github__create_pull_request

A bare server name such as mcp__atlassian has no tool segment and stays as
written.

Tool identifiers inside URLs and paths must never be flagged or rewritten:
the schema catalog at
https://mcp.example.com/tools/mcp__plugin_github_github__create_pull_request
documents every argument.

Prose that instructs configuration keeps the fully-qualified name — add
`mcp__plugin_github_github__create_pull_request` to the allowed-tools list
before using the release workflow.

Configuration examples keep the fully-qualified identifier, so nothing in
the block below is rewritten:

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
