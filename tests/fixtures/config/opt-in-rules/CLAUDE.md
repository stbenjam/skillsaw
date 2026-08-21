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

## Using the search tool

When you need to find a symbol, use the search tool. For example:

```
search(query="ProvisionFlange", type="symbol")
```

Another example, searching for a file:

```
search(query="flange.go", type="file")
```

A third example, searching text:

```
search(query="torque limit", type="text")
```

## Reviewing changes

Show the current changes with !`git diff HEAD` before reviewing the pull request.
