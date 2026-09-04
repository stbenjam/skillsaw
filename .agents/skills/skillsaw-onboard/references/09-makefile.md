# Add Makefile targets

Resolve the latest version to pin:

```console
python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/skillsaw/json', timeout=10))['info']['version'])"
```

If `python3` is unavailable or the lookup fails:

```console
git ls-remote --refs --tags --sort='v:refname' https://github.com/stbenjam/skillsaw.git 'v[0-9]*.[0-9]*.[0-9]*' | grep -E 'refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' | tail -1 | sed 's|.*refs/tags/v||'
```

A floating `v0` tag exists beside the releases, which is what the pattern and
the `grep` keep out. The result must look like `N.N.N`; if it does not, stop
and report the value.

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
	$(CONTAINER_ENGINE) run --rm -v $$(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw:$(SKILLSAW_VERSION) --strict

lint-fix:
	$(CONTAINER_ENGINE) run --rm $(if $(findstring podman,$(CONTAINER_ENGINE)),--userns=keep-id,) --user $$(id -u):$$(id -g) -v $$(pwd):/workspace:Z ghcr.io/stbenjam/skillsaw:$(SKILLSAW_VERSION) fix
```

Append to an existing `Makefile` or create one. Never overwrite existing
`lint` or `lint-fix` targets; ask the user for alternate names when they
collide. Record the chosen targets, then return to the router.
