# deployment-tools

A Claude Code plugin for managing application deployments across
staging and production environments.

## Installation

```bash
claude plugin install deployment-tools
```

## Commands

- `/deployment-tools:deploy` — Deploy to a target environment
- `/deployment-tools:rollback` — Roll back the most recent deployment
- `/deployment-tools:status` — Show deployment status for all environments

## Skills

- `code-review` — Review code changes for quality issues
- `release-notes` — Generate release notes from the git log

## Agents

- `reviewer` — Perform thorough code reviews on pull request diffs

## Configuration

The plugin reads `deploy.yaml` from the repository root for environment
definitions. Each environment needs a `cluster`, `namespace`, and
`rollout_strategy` key.
