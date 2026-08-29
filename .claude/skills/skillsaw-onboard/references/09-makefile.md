# Add Makefile targets

Resolve the latest version to pin:

```console
python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/skillsaw/json'))['info']['version'])"
```

If `python3` is unavailable:

```console
git ls-remote --tags https://github.com/stbenjam/skillsaw.git 'v*' | sort -t/ -k3 -V | tail -1
```

Ask whether to use uvx or the installed container runtime.

## uvx

```makefile
SKILLSAW_VERSION := <LATEST_VERSION>

.PHONY: lint lint-fix
lint:
	uvx skillsaw==$(SKILLSAW_VERSION) --strict

lint-fix:
	uvx skillsaw==$(SKILLSAW_VERSION) fix
```

## Podman or Docker

```makefile
SKILLSAW_VERSION := <LATEST_VERSION>
CONTAINER_ENGINE ?= $(shell command -v podman 2>/dev/null || echo docker)

.PHONY: lint lint-fix
lint:
	$(CONTAINER_ENGINE) run --rm -v $$(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw:v$(SKILLSAW_VERSION) --strict

lint-fix:
	$(CONTAINER_ENGINE) run --rm -v $$(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw:v$(SKILLSAW_VERSION) fix
```

Append to an existing `Makefile` or create one. Never overwrite existing
`lint` or `lint-fix` targets; ask the user for alternate names when they
collide. Record the chosen targets, then return to the router.
