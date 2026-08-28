## Why

An agent asked to "read the upgrade notes at this URL" cannot tell a dead
link from a live one. It follows the link, gets an error page or nothing at
all, and continues on whatever it already believed — the context file
promised grounding it silently failed to deliver. Human readers get a 404.

Dead external links accumulate the same way dead internal ones do: a
vendor reorganizes its documentation, a repository is renamed, a blog
migrates. Nothing in the referencing file changes, so nothing signals the
rot.

## Why this rule is opt-in

It is the only rule in skillsaw that opens a network connection, so it is
off unless you turn it on (`default_enabled = false`, never `auto`). A
lint run is hermetic by default: no repository type, no detected format,
and no `enabled: auto` setting will start making requests on your behalf.

That also makes it a poor fit for a per-PR gate. Enable it in a scheduled
job instead — see the CI recipe below.

## What counts as broken

Only two answers from the server are treated as evidence:

| Status | Verdict |
|---|---|
| `404 Not Found` | Violation |
| `410 Gone` | Violation |

Everything else is *not* a violation, deliberately:

- `401`, `403`, `429` — bot walls and rate limits. A site that blocks the
  CI runner's user agent says nothing about whether the link works for a
  human.
- `5xx` — the origin is having a bad day.
- Timeouts, DNS failures, refused connections, TLS errors — the network
  between the runner and the host, not the link.
- Redirect chains longer than five hops, and redirects that leave
  `http`/`https`.

A linter that fails your build because a documentation site rate-limited
your runner is worse than no linter at all.

## Examples

**Bad:**

```markdown
Follow the [migration guide](https://example.com/docs/removed-page) before
upgrading the client.
```

**Good:**

```markdown
Follow the [migration guide](https://example.com/docs/migrating) before
upgrading the client.
```

## What is checked

- `http` and `https` links from the markdown AST: inline links, reference
  links, autolinks (`<https://…>`), and image destinations. Links inside
  fenced or indented code blocks are not links, so they are never
  requested.
- Bare URLs in prose that are not written as links are **out of scope** —
  they are text, not references.
- URLs carrying credentials (`https://user:token@host/…`) are skipped
  entirely rather than requested.
- Files under a `template/`, `templates/`, or `_template/` directory are
  skipped, exactly as `content-broken-internal-reference` skips them:
  placeholder targets there are intentional.

Each distinct URL is requested once per run, however many files mention
it, and every occurrence is still reported with its own file and line.

## Network behavior

A `HEAD` request first; if the server answers `405` or `501`, one `GET`
retry, reading the status and headers and never the body. Redirects are
followed up to five hops. Requests run on a small thread pool and identify
themselves as `skillsaw/<version>`.

Two limits bound a run: `timeout` per request and `total-budget` for all
of them together. When the budget runs out, the URLs still queued are left
unchecked and the run emits one info-level notice saying how many — never
one per URL.

## How to fix

Open the URL. If the page moved, update the link to its new address. If
the resource is gone for good, remove the reference or replace it with one
that still resolves — an agent reading the file needs the content, not the
address it used to live at.

If the URL is fine and the failure is the checker's (a staging host only
reachable from your network, a URL built from a template placeholder), add
it to `ignore`. Entries containing `*`, `?`, or `[` are matched as globs;
anything else is matched as a literal prefix:

```yaml
rules:
  content-broken-external-reference:
    enabled: true
    ignore:
      - https://internal.example.com/          # prefix
      - https://*.staging.example.net/*        # glob
```

Note that *any* setting for this rule — even just `ignore` or `timeout` —
enables it, because it is disabled by default. To configure it without
turning it on, keep an explicit `enabled: false`.

### CI recipe

Run it on a schedule rather than on every pull request, so a flaky origin
can never block a merge:

```yaml
name: link-check
on:
  schedule:
    - cron: "0 6 * * 1"   # Mondays, 06:00 UTC
  workflow_dispatch:

jobs:
  links:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pipx install skillsaw
      - run: skillsaw lint . --rule content-broken-external-reference
```

`--rule` enables the rule for that run without committing it to
`.skillsaw.yaml`, so your per-PR lint stays offline.
