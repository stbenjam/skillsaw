# Project Standards

widgetworks-api is a Flask service that powers the widget catalog. Use
these notes for every change in this repository.

## Development environment

Install dependencies with `pip install -r requirements-dev.txt` into a
virtualenv at `.venv`, then run `make bootstrap` once to seed the
development database. All commands below assume the virtualenv is
active. Local configuration is TOML-based; copy the checked-in example
file on first setup and keep secrets out of git.

## Testing

Run `make test` before every push. The integration suite needs the
Postgres container: start it with `make db-up` and stop it with
`make db-down` when you are done. Mark slow tests with the `slow`
marker so CI can shard them separately, and never delete a failing test
to make the suite pass. Quarantine flaky tests with the `flaky` marker
and link the tracking issue in the marker reason. Coverage must stay
above 80 percent; check the report with `make coverage` before
requesting review.

## Code review

Keep PRs under 400 changed lines where practical and write the
description as problem, then solution, then testing evidence. Squash
fixup commits before requesting review. Every schema migration needs a
rollback note in the PR description and a reviewer from the data team.
