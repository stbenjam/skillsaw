# Pipeline Service Guidelines

This service is a Flask API that manages deployment pipelines. Run
`make test` before every commit and `make lint` before pushing.

## Code Standards

- Try to keep functions under 50 lines.
- Be careful when editing the migration scripts in `db/migrations/`.
- Format code with `black --line-length 100` before committing.
- Type annotations are required on all public functions.

## Deployment

1. Run `make build` to produce the container image
2. Push the image with `make push`
3. Trigger the rollout with `scripts/deploy.sh production`

## Dependencies

- Add runtime dependencies to `pyproject.toml` under `[project.dependencies]`
- Pin major versions only: `requests>=2.28,<3`
