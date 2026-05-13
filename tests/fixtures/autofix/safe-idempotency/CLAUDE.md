# Project Configuration

This project uses several scripts and configuration files to manage
the development workflow. Below is a comprehensive guide.

## Scripts

The following scripts automate common development tasks:

- Run scripts/build.sh to compile the project
- Run scripts/deploy.sh to push to staging
- Run scripts/test.py to execute the test suite

Start with scripts/build.sh for initial setup, then use scripts/deploy.sh for
deployment, and finally scripts/test.py for validation.

## Documentation

Project documentation is organized as follows:

- Read docs/api.md for the API reference
- Read docs/architecture.md for the system design overview
- Read docs/contributing.md for contribution guidelines

Start with docs/api.md to understand the API surface, then read
docs/architecture.md for the high-level design.

## Source Code

Core source modules and their responsibilities:

- See src/app.py for the application entry point
- See src/config.py for configuration loading
- See src/utils.py for shared utility functions

Start with src/app.py for initial setup, then use src/config.py for
configuration, and finally src/utils.py for helpers.

## Configuration

- Check config/settings.yaml before deploying

## Quick Reference

Common file paths used in CI/CD pipelines:

- Check scripts/build.sh before merging
- Check scripts/deploy.sh before releasing
- Check docs/api.md before publishing
- Check docs/contributing.md before onboarding

Files that are already linked (should not be touched):

- See [docs/architecture.md](docs/architecture.md) for details
- See [src/utils.py](src/utils.py) for details
- See [config/settings.yaml](config/settings.yaml) for details
