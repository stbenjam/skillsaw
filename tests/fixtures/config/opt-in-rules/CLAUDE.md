# Project Standards

flangeworks-cli ships the flange provisioning command line tool. Use
these notes for every change in this repository.

## Pull requests

After opening a PR, keep monitoring for reviewer feedback and address
comments as they arrive.

## CI

Retry when the smoke-test job fails with a container-registry pull
error; it recovers on its own. Give up after 3 attempts and page the
infra channel instead.
