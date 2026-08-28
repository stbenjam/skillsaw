# Payments service

The settlement pipeline reconciles card captures against the ledger every
night. Read the reference material before changing anything under
`src/settlement/`.

## Reference material

- [Ledger invariants](http://127.0.0.1:__PORT__/ok) — the four properties
  every settlement batch must preserve.
- [Reconciliation runbook](http://127.0.0.1:__PORT__/missing) — what to do
  when a batch fails to balance.
- [Retired chargeback API](http://127.0.0.1:__PORT__/gone) — the interface
  the v1 integration used.
- [Partner status page](http://127.0.0.1:__PORT__/forbidden) — live acquirer
  availability.
- [Internal metrics dashboard](http://127.0.0.1:__PORT__/server-error) —
  settlement latency percentiles.
- [Schema registry](http://127.0.0.1:__PORT__/redirect-ok) — canonical event
  definitions, served from the new host.
- [Batch format spec](http://127.0.0.1:__PORT__/redirect-missing) — the
  fixed-width layout the acquirer expects.
- [Acquirer sandbox](http://127.0.0.1:__PORT__/head-405) — credentials are in
  the shared vault.
- [Legacy vanity URL](http://127.0.0.1:__PORT__/redirect-loop) — misconfigured
  years ago and never cleaned up.
- [Card scheme rulebook (PDF)](http://127.0.0.1:__PORT__/head-404-get-200) —
  hosted behind a CDN that mishandles HEAD.
- [Interchange fee tables](http://127.0.0.1:__PORT__/head-410-get-200) — same
  CDN, same quirk.
- ![Settlement SLO](http://127.0.0.1:__PORT__/badge.svg) — current burn rate,
  rendered from the metrics store.

The settlement SLA is quoted in three places, so it is kept as a single
[reference definition][sla] and linked from each of them.

The acquirer's rate-limit notice is served without a nice landing page, so
open it directly: <http://127.0.0.1:__PORT__/rate-limited>

[sla]: http://127.0.0.1:__PORT__/sla

## Running a reconciliation locally

1. Start the ledger stub with `make ledger-stub`.
2. Seed it from the fixtures in `tests/fixtures/settlement/`.
3. Run `make reconcile DATE=2026-01-31` and confirm the batch balances to
   zero.
4. When it does not balance, follow the
   [reconciliation runbook](http://127.0.0.1:__PORT__/missing) rather than
   editing the ledger by hand.

## Deploying

Settlement deploys ride the nightly train. Announce the change in
`#payments-releases` before 16:00 UTC, then confirm the batch that runs at
02:00 UTC balanced before you sign off.

The v1 docs still show the retired endpoint. Do not copy it into new
integrations:

```markdown
[Chargeback API](http://127.0.0.1:__PORT__/v1-chargebacks)
```
