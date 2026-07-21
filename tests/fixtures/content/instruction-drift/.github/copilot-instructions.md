# Copilot Instructions

widgetworks-api is a Flask service that powers the widget catalog.

## Code style

Format Python with `black` and lint with `ruff`; both run via
`make format` and `make lint`. Type annotations are required on public
functions, and new modules must pass `mypy --strict`. Keep view
functions thin — business logic belongs in `services/`, not in route
handlers.

## Testing

Run `make test` before every push. The integration suite needs the
Postgres container: start it with `make db-up` and stop it with
`make db-down` when you are done. Mark slow tests with the `slow`
marker so CI can shard them separately, and never delete a failing test
to make the suite pass. Quarantine flaky tests with the `flaky` marker
and link the tracking issue in the marker reason.
