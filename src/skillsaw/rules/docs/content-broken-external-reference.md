## Why

A markdown link to a page that no longer exists is a dead reference. An
agent told to read it cannot tell one from a live link: it follows the
link, gets an error page, and carries on with whatever it already
believed instead of the grounding the file promised. Dead external links
accumulate the way dead internal ones do — a vendor reorganizes its docs,
a repository is renamed, a blog migrates — and nothing in the referencing
file changes, so nothing signals the rot.

## Why this rule is opt-in

It is the only rule in skillsaw that opens a network connection, so it is
off unless you turn it on (`default_enabled = false`, never `auto`). A
lint run is hermetic by default: no repository type, no detected format,
and no `enabled: auto` setting will start making requests on your behalf.
For a disabled-by-default rule, **any** setting under its config key
activates it — a lone `ignore:` or `severity:` is enough — so to tune it
without turning it on, keep an explicit `enabled: false`.

A flaky origin makes it a poor fit for a per-PR gate; run it on a
schedule instead (see the CI recipe below). Enabling it in
`.skillsaw.yaml` rather than with `--rule` has a second, stickier
consequence: violations are warnings, warnings are weighted into the
letter grade, so your `skillsaw badge` output becomes a function of
whether a third-party URL 404s today.

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
GitHub Action sets `no-network: 'true'` by default and treats anything
but the literal `false` as a request to keep the network off. Naming only
gated rules under the flag is an error, not a run that checks nothing and
exits 0.

`fix` never runs a network rule at all, flag or no flag: a dead URL has
no mechanical fix, and the autofix loop re-runs every rule's `check()`
once per pass, so probing there would sweep the whole URL set several
times over and discard every answer. Diagnose this rule with
`skillsaw lint`.

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
private, link-local, reserved, multicast or unspecified address — or a
`localhost` name — is refused, as is any address `ipaddress` does not call
global. That last one is not redundant: RFC 6598 carrier-grade NAT
(`100.64.0.0/10`) is excluded from `is_global` and from no other
predicate, and it is the range Tailscale uses along with several
managed-Kubernetes pod CIDRs. An IPv4-mapped IPv6 address is unwrapped to
its IPv4 form first and classified by that, so `::ffff:127.0.0.1` is
refused as loopback while `::ffff:8.8.8.8` is allowed like any other
public address. So are the other spellings of those addresses, because the
host is classified the way the transport will spell it rather than the way
the link is written, without performing a lookup:

- the forms a resolver accepts and `ipaddress` does not —
  `http://2852039166/`, `http://0x7f000001/`, `http://0177.0.0.1/`,
  `http://127.1/` — are normalized through `inet_aton`;
- the forms urllib *decodes* before it connects — `http://169%2E254%2E169%2E254/`,
  `http://loc%61lhost/`, and the full-width and ideographic-dot spellings
  such as `http://169。254。169。254/` — are percent-decoded and IDNA-encoded
  first, which is what `Request` and `getaddrinfo` do on the way to the
  socket. A host the IDNA codec cannot encode is refused rather than
  guessed at.

Two spellings are refused *after* that encoding, because both would make
the classified host differ from the connected-to one. A host still
carrying a `%` — `http://169.254.169.254%253A80/`, or the single
full-width `％3A` that nameprep's NFKC step folds to `%` — is refused,
because urllib percent-decodes a second time and `http.client` then reads
a decoded `:` as a port. So is a host carrying a control character, which
the IDNA codec's ASCII fast path passes through verbatim and
`getaddrinfo` truncates at. For the same reason userinfo is rejected
after canonicalization rather than before: decoding `user%40example.com`
is what creates it, and a port that is not simply digits —
`169.254.169.254:80%40x` — is refused whole, because that same decode
turns the tail into userinfo.

The requested URL carries that canonical host, so `ignore` matches what
actually goes on the wire. The URL in the *report* is the href as
authored — that is the string you have to find in the file — so it can
differ from the wire, and does routinely: the fragment is dropped from
the request but kept in the message, and the host is lowercased and
punycoded on the wire but not in the message. The check re-runs on every
redirect hop, so an origin cannot redirect the linter onto your internal
network.

Lifting the confinement is the operator's call, not the repository's:
`skillsaw lint . --allow-private-hosts`, or `SKILLSAW_ALLOW_PRIVATE_HOSTS=1`.
There is deliberately no `.skillsaw.yaml` key — the repository is the actor
the confinement exists to contain, so a setting it could write would not be
a control at all. An internal *hostname* that resolves to a private address
is not caught (that would need a resolver lookup, and would still lose to
DNS rebinding); `--no-network` and egress control are what cover it.
`HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` are honored.

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
- **Every input is hostile**: URLs come from repo content, options from a
  repo-controlled `.skillsaw.yaml`. Confine destinations to public hosts,
  re-run admission on every redirect hop, and clamp each option with a
  named `_MAX_*` constant, as `_MAX_REGEX_TIMEOUT` does for T13.
- **Tests run against a local `http.server`**, never the internet, with
  the markdown in fixtures. Keep the guard that a default run makes no
  requests, and assert it on a recorded ledger rather than a raised
  exception — `Linter.run` turns exceptions into violations. Add the rule
  to `NETWORK_RULES` in `tests/test_integration.py` with the companion
  test that it fires against the local server.

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

Redirects are followed up to five hops. Requests run on a small pool of
daemon threads and identify themselves as
`skillsaw/<version> (+https://skillsaw.org)`.

Two limits bound a run. `timeout` is the socket timeout for a single
request, so it bounds each read rather than a whole request — a slow
header stream can cost several multiples of it. `total-budget` is the wall
clock for all requests together, and it is what actually bounds the run:
workers are joined against it and any still running when it expires are
abandoned, on daemon threads that cannot hold the process open at exit.
There is no way to switch the budget off; `0` and negatives mean the
default, and the value is clamped.

When the budget runs out, the URLs still queued are left unchecked and the
run emits one info-level notice — one per run, never one per URL. It says
that some URLs went unchecked but not how many: it has no file path, so
its baseline identity is a hash of its message, and a count that moved
with runner latency would re-fingerprint it every run. Run with `-v` for
the count.

### Deliberately not a general link checker

Anchor and fragment checking, response caching between runs, retry and
backoff, configurable accepted status ranges, and authenticated requests
are all out of scope. This rule exists to catch link rot in agent context
files with skillsaw's reporting — `explain`, baselines, suppressions,
severity, the grade — around it. For a full-featured link checker over a
whole documentation tree, use [lychee](https://github.com/lycheeverse/lychee)
or [markdown-link-check](https://github.com/tcort/markdown-link-check).

## How to fix

Open the URL. If the page moved, update the link to its new address; if
the resource is gone for good, remove the reference or replace it with one
that still resolves — an agent reading the file needs the content, not the
address it used to live at.

If the URL is fine and the failure is the checker's (a staging host only
reachable from your network, a URL built from a template placeholder), add
it to `ignore`. Entries containing `*`, `?`, or `[` are matched as globs;
anything else as a literal prefix:

```yaml
rules:
  content-broken-external-reference:
    enabled: true
    ignore:
      - https://internal.example.com/          # prefix
      - https://*.staging.example.net/*        # glob
```

Patterns are matched against the URL that is actually requested, which has
had its fragment stripped and its host percent-decoded, punycoded and
lowercased, so write entries without a `#fragment` — one that carries a
fragment never matches — and spell the host the way DNS sees it.

Both operands are size-bounded, because both come from the repository: a
pattern over 256 characters is skipped (the URLs it would have matched are
probed rather than ignored) and a URL over 2,048 characters is never
requested. Neither is reported, and nothing written on purpose comes near
either bound.

### CI recipe

Run it on a schedule rather than on every pull request, so a flaky origin
can never block a merge. The workflow to copy is in the
[CI guide](https://skillsaw.org/ci/#scheduled-external-link-checking) —
it uses the dedicated `stbenjam/skillsaw/link-check` Action, which owns the
network grant, strict threshold, and deduplicated issue reporting. The
repository's workflow supplies only the schedule and permissions.
