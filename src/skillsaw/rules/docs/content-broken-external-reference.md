## Why

A markdown link to a page that no longer exists is a dead reference. An
agent told to read it cannot tell a dead link from a live one: it follows
the link, gets an error page, and carries on with whatever it already
believed instead of the grounding the file promised. A human reader gets
a 404.

Dead external links accumulate the same way dead internal ones do: a
vendor reorganizes its documentation, a repository is renamed, a blog
migrates. Nothing in the referencing file changes, so nothing signals the
rot.

## Why this rule is opt-in

It is the only rule in skillsaw that opens a network connection, so it is
off unless you turn it on (`default_enabled = false`, never `auto`). A
lint run is hermetic by default: no repository type, no detected format,
and no `enabled: auto` setting will start making requests on your behalf.

Be aware that for a disabled-by-default rule, **any** setting under its
config key activates it — a lone `ignore:` or `severity:` is enough. To
tune it without turning it on, keep an explicit `enabled: false`.

That also makes it a poor fit for a per-PR gate. Enable it in a scheduled
job instead — see the CI recipe below. Enabling it in `.skillsaw.yaml`
rather than with `--rule` has a second, stickier consequence: violations
are warnings, warnings are weighted into the letter grade, so your
`skillsaw badge` output becomes a function of whether a third-party URL
404s today.

## The operator's gate

The rule's `enabled` state is decided by the linted repository's
`.skillsaw.yaml` — which skillsaw's [threat model](https://github.com/stbenjam/skillsaw/blob/main/THREAT_MODEL.md)
treats as untrusted content. Whether skillsaw may touch the network at
all is decided by the operator instead:

```console
$ skillsaw lint . --no-network     # also: SKILLSAW_NO_NETWORK=1
```

`--no-network` is available on `lint`, `fix`, `baseline`, and `badge`. It
drops every rule that declares `requires_network`, whatever the
repository's config or a `--rule` flag asks for, so an air-gapped or
enterprise CI job can assert "skillsaw made no network calls" from a flag
rather than by auditing every linted repository's YAML. The shipped
GitHub Action sets `no-network: 'true'` by default for the same reason.

When the network *does* engage, skillsaw says so on stderr:

```console
⚠ Network access enabled for: content-broken-external-reference (use --no-network to skip)
```

## What is sent, and to whom

Enabling this rule discloses, to every third-party host referenced
anywhere in your context files:

- **your runner's IP address**, and that the repository is being linted —
  on a schedule, repeatedly;
- **the full path and query string** of each URL. Only the fragment is
  dropped. A URL like `https://host/doc?access_token=…`, or a
  pre-signed link, is transmitted intact. URLs carrying *userinfo*
  (`https://user:token@host/…`) are skipped entirely — but that promise
  does not extend to secrets in a query string;
- **the user agent** `skillsaw/<version> (+https://skillsaw.org)`, which
  identifies the tool and its version.

Destinations are confined to public hosts. A URL whose host is a loopback,
private, link-local, reserved, multicast or IPv4-mapped address — or a
`localhost` name — is refused unless you set `allow-private-hosts: true`.
The same check re-runs on every redirect hop, so an origin cannot redirect
the linter onto your internal network. An internal *hostname* that resolves
to a private address is not caught (that would need a resolver lookup, and
would still lose to DNS rebinding); use `--no-network` or network egress
control if that matters.

`HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` are honored, so a restricted-egress
environment can route or block these requests the usual way.

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
- `5xx` — a transient origin failure.
- Timeouts, DNS failures, refused connections, TLS errors — the network
  between the runner and the host, not the link.
- Redirect chains longer than five hops, and redirects that leave
  `http`/`https`.
- A `404`/`410` that a follow-up `GET` does not confirm (see below).


## Invariants for a future network rule

This is the only rule in skillsaw permitted to open a connection
(`THREAT_MODEL.md` T18). Anything that follows it must keep all of these:

- **`requires_network = True`** — the whole operator gate reads that one
  attribute (`--no-network`, the Action's `no-network` default, and
  `scripts/changed-rules.py`, which keeps `rule-impact.yml` from
  force-running network rules against third-party repositories). Never
  replace it with a rule-id list.
- **`default_enabled = False`, never `auto`**, and the standard library
  only — no new dependency for a request.
- **Only definitive evidence is a violation.** Everything the network
  can say about itself stays silent.
- **Every input is hostile**: URLs come from repo content and options
  from a repo-controlled `.skillsaw.yaml`. Confine destinations to
  public hosts, re-run admission on every redirect hop, and clamp each
  option with a named `_MAX_*` constant, as `_MAX_REGEX_TIMEOUT` does
  for T13.
- **Tests run against a local `http.server`**, never the internet, with
  the markdown in fixtures. Keep the guard that a default run makes no
  requests, and assert it on a recorded ledger rather than a raised
  exception — `Linter.run` turns exceptions into violations. Add the
  rule to `NETWORK_RULES` in `tests/test_integration.py` with the
  companion test that it fires against the local server.

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

A `HEAD` request first, reading the status and headers and never the body.
The answer is re-asked with `GET` in two cases:

- the server answers `405` or `501` — it refuses `HEAD` outright;
- the answer was `404` or `410` — a candidate violation.

The second case matters more than it looks. RFC 9110 says a `HEAD`
response must be what `GET` would return minus the body, and a fair number
of servers do not comply: NIST's publication host answers `404` to `HEAD`
and serves the PDF on `GET`. **A `HEAD` alone is never enough to convict** —
`GET` is the authoritative answer, and if it does not also say `404`/`410`,
nothing is reported. The extra request is paid only for links about to be
flagged, so it costs nothing on a healthy repository.

Redirects are followed up to five hops. Requests run on a small thread pool
and identify themselves as `skillsaw/<version>`.

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

*Any* setting for this rule — `ignore` or `timeout` alone, and even an
unrecognized key — enables it, because it is disabled by default. To
configure it without turning it on, keep an explicit `enabled: false`.

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
