# Contributing to skillsaw

Contributions welcome! Here's how to get started.

## Getting started

1. Fork the repository
2. Clone your fork and create a feature branch
3. Set up the development environment: `make venv`
4. See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed setup, testing, and workflow instructions

## Making changes

- Add tests for new functionality
- Run `make test` to verify all tests pass
- Run `make lint` to check formatting (or `make format` to fix)
- Run `make update` to regenerate all generated files

## Submitting a pull request

1. Ensure all tests pass and formatting is clean
2. Run `make update` — the `verify-update` CI check will fail if generated files are stale
3. Write a clear PR description explaining the change and motivation
4. Submit the pull request

## Writing new rules

See [DEVELOPMENT.md](DEVELOPMENT.md#writing-new-rules) for the full guide on adding linter rules.

## AI-assisted development

This project uses [APM](https://agentskills.io) to provide context for AI coding assistants.
Contributors using Claude Code, Cursor, Gemini, or OpenCode will automatically get project
instructions and skills loaded.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
