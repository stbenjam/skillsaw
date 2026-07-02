# Project Standards

This repository contains the inventory service. Follow these instructions
when making changes.

## Build and test

- Build with `make build`; run unit tests with `make test`.
- Run `make integration` before opening a pull request.

## Code conventions

- Handlers live in `internal/api/`; one file per resource.
- Database access goes through the repository layer in `internal/store/`.
