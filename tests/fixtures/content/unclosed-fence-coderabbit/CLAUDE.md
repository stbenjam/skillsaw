# widgetworks-api

Flask service powering the widget catalog. Use these notes for every
change in this repository.

## Deploying

Deploy with:

```bash
make deploy ENV=staging

## Rollback

Roll back with `make rollback ENV=staging` within 5 minutes of a bad
deploy, then page the on-call channel with the release tag.
