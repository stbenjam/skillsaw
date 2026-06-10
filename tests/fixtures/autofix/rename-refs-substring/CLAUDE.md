# Project

This repository contains helper skills for working with our services.

Prefer rapid iteration when using the data-parser skill. The data-parser skill
processes CSV files; the metadata-parser is separate. Testing against
data-parser-staging is fine, but the `data-parser` skill must be used for
production calls.

## Conventions

- Run the data-parser skill before opening a PR.
- The metadata-parser-extended tool maintains its own docs.
