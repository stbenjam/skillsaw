# Widget Dashboard

<img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iI2ZmNmIzNSIgZD0iTTEyIDJMMiA3djEwbDEwIDUgMTAtNVY3bC0xMC01em0wIDIuMmw3LjUgMy43NXY3LjZMMTIgMTkuM2wtNy41LTMuNzV2LTcuNkwxMiA0LjJ6Ii8+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMy40IiBmaWxsPSIjMWQzNTU3Ii8+PC9zdmc+" alt="Widget Dashboard logo" width="48">

Internal dashboard for widget telemetry. Python 3.12 + FastAPI backend with
a React frontend in `web/`.

## Development

- Install dependencies with `make setup` (creates `.venv`).
- Run the API locally with `make run`; the frontend dev server proxies to it
  on port 8000.
- Run `make test` before pushing. CI runs the same target on 3.11 and 3.12.

## Conventions

- Keep API handlers in `app/routes/` thin; business logic belongs in
  `app/services/`.
- Frontend components use the shared design tokens in `web/src/tokens.ts`.
- Database migrations are generated with `make migration` and reviewed by a
  human before merge.
