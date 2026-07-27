## Why

Command files follow a structured format with four recommended
sections: Name, Synopsis, Description, and Implementation. Missing
sections make the command harder for both humans and agents to
understand — the format exists so that each piece of information
has a predictable location.

## Examples

**Bad:**

```markdown
---
description: Deploy to staging
---

Run `make deploy-staging` to deploy.
```

**Good:**

```markdown
---
description: Deploy to staging
---

## Name

my-plugin:deploy-staging

## Synopsis

Deploy the application to the staging environment.

## Description

Runs the staging deployment pipeline...

## Implementation

Run `make deploy-staging`.
```

## How to fix

Add the missing section heading(s) listed in the violation message.
Each section is a `##` heading with the exact name shown.

## Codex plugins

This is a Claude-format convention. A directory claimed only by OpenAI
Codex — a `.codex-plugin/plugin.json`, or a local-source listing in a
Codex catalog, with no `.claude-plugin` marker or Claude marketplace
listing — is exempt: Claude never loads it, so Claude command section conventions do not apply to its commands/. A dual-manifest
directory keeps this check, and the ecosystem-neutral content and
security rules read every plugin's files regardless of provenance.
