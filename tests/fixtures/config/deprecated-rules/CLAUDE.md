# Project Instructions

This service powers the internal billing dashboard. Use these notes when
making changes anywhere in the repository.

## Environment

Install dependencies with `make deps` before running anything else. The
project targets Python 3.11; older interpreters fail on the pattern-match
syntax in the scheduler module.

Configuration lives in `config/settings.toml`. Local overrides belong in
`config/settings.local.toml`, which is gitignored.

## Development Workflow

Run `make test` after each change. The suite is fast because the database
layer is faked in unit tests; integration tests live behind `make
integration` and need a running Postgres.

Format code with `make format` before committing. CI rejects unformatted
code, so running it locally saves a round trip.

Branch names follow `feature/<ticket-id>-short-description`. Commit
messages use the imperative mood with the ticket id in the footer.

IMPORTANT: Never run schema migrations against the shared staging
database without coordinating in the #billing channel first.

## Release Process

Releases cut from `main` every Tuesday. The release manager tags the
commit, and the deploy pipeline promotes it through staging to
production over roughly two hours.

Hotfixes branch from the latest release tag, not from `main`. After the
hotfix ships, cherry-pick the commit back to `main` so the fix is not
lost in the next release.

## Observability

Dashboards live in Grafana under the `billing` folder. Alerts route to
PagerDuty; the escalation policy pages the on-call engineer first and
the team lead after fifteen minutes.

When investigating an incident, start from the request-rate panel and
correlate with the deploy markers before digging into traces.

## Support Rotation

The support rotation changes every Monday. The engineer on rotation
triages new issues, answers questions in the #billing channel, and
files tickets for anything that needs deeper work.
