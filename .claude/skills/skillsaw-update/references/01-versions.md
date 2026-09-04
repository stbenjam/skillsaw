# Resolve versions and upgrade

Record the installed version first; nothing below upgrades until the old
rule list is captured in the next section.

## Installed version

Run `skillsaw --version`. If it works, retain that command prefix (`skillsaw`)
as `<installed-prefix>` and note the version as `{installed}`.

If `skillsaw --version` is not found or fails, look for the version the
repository itself runs before installing anything: a `uvx skillsaw==N.N.N` or
`SKILLSAW_VERSION` in a Makefile or CI file, or a `ghcr.io/stbenjam/skillsaw`
image tag. When one exists, that command (`uvx skillsaw==N.N.N` for a plain
version) is `<installed-prefix>` and its version is `{installed}`, so the old
rule list below is the one the repository really runs. When nothing pins a
version, resolve `{latest}` first (see below), then bootstrap pinned to that
version: prefer zero-install execution with `uvx skillsaw=={latest}`, then
`pip install "skillsaw=={latest}"`, then the installed container runtime. For
containers, `<installed-prefix>` is a complete run command mounting the
repository at `/workspace`:

```console
podman run --rm --userns=keep-id --user "$(id -u):$(id -g)" -v "$PWD:/workspace:Z" ghcr.io/stbenjam/skillsaw:{latest}
```

or, with Docker:

```console
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/workspace:Z" ghcr.io/stbenjam/skillsaw:{latest}
```

Image tags carry no `v`: release `0.19.0` is the image tag `0.19.0`. The image
runs as a non-root user, so both commands map the invoking user in to keep the
later `fix` and `baseline` steps able to write; rootless Podman additionally
needs `--userns=keep-id` for that mapping to reach the host user, and `:Z`
relabels the mount on SELinux hosts (elsewhere the label is ignored). Verify
with `<installed-prefix> --version` and treat the version it prints as
`{installed}`. If `python3` is unavailable for the PyPI lookup below, use its
git fallback.

## Latest version

Resolve the newest release to `{latest}`:

```console
python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/skillsaw/json', timeout=10))['info']['version'])"
```

If PyPI is unreachable, read the newest release tag instead. Release tags
carry a `v`, and floating tags such as `v0` exist beside them, so the pattern
asks for three numeric parts, the `grep` drops prerelease tags such as
`v0.21.0-rc1`, and `--refs` leaves the peeled `^{}` lines out:

```console
git ls-remote --refs --tags --sort='v:refname' https://github.com/stbenjam/skillsaw.git 'v[0-9]*.[0-9]*.[0-9]*' | grep -E 'refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' | tail -1 | sed 's|.*refs/tags/v||'
```

`{latest}` must look like `N.N.N`. If it does not, stop and report the value
rather than passing it to `pip`, `uvx`, an image tag or a pin.

If `{installed}` equals `{latest}`, report that the install is current (after
a bootstrap above: that the bootstrap already runs the newest release), retain
`<installed-prefix>` as `<new-prefix>`, skip the upgrade question below, and
continue from "Capture the old rule list": there are no new rules, but pins
may still lag behind.

## Capture the old rule list

Before upgrading, save the rule IDs the installed version knows:

```console
<installed-prefix> list-rules > /tmp/skillsaw-rules-old.txt
```

Keep this file; the next section diffs it against the new version.

## Upgrade

Ask before changing the local environment:

> Installed skillsaw is {installed} and the newest release is {latest}.
> Should I upgrade the local install?

If yes, apply the method below that matches the retained prefix; if no, skip
to "Declining the upgrade".

## Upgrade methods

- **Project dependency**: when the prefix resolves inside the repository's
  own `.venv`, or a `uv.lock`, `poetry.lock` or `Pipfile.lock` lists
  skillsaw, the version lives in the manifest, so this is a pin edit made
  with the user's consent: keep the dependency group and the operator the
  manifest uses (`uv add --dev` and `poetry add --group dev` would move the
  entry and replace a caret or floor), set an exact pin to `{latest}` and
  leave a floor or caret unless the user chooses to raise it, then move the
  lock with the scoped
  command (`uv lock --upgrade-package skillsaw`,
  `poetry update --lock skillsaw`, `pipenv update skillsaw`). The project's
  own invocation (`uv run skillsaw`, `poetry run skillsaw`,
  `pipenv run skillsaw`) is `<new-prefix>`.
- **uvx**: nothing to install. The new prefix is `uvx skillsaw=={latest}`;
  the old one stays usable for comparison.
- **pip, pipx or uv tool**: identify the manager first; the first line of
  the `skillsaw` script (`head -1 "$(command -v skillsaw)"`) names its
  interpreter (`…/pipx/venvs/skillsaw/…`, `…/uv/tools/skillsaw/…`, or a
  plain virtualenv). Then upgrade with that manager, keeping the rule
  plugins it carries: `pipx upgrade skillsaw` keeps injected packages;
  `uv tool install "skillsaw=={latest}"` with one `--with <plugin>` per
  extra requirement `uv tool list --show-with` prints, since a reinstall
  replaces the environment and `uv tool upgrade` keeps a pinned install's
  constraint without upgrading; `pip install "skillsaw=={latest}"` leaves
  the environment's other packages alone. Retain `skillsaw` as
  `<new-prefix>`.
- **Container**: pull the pinned image
  (`podman pull ghcr.io/stbenjam/skillsaw:{latest}` or `docker pull ...`) and
  define `<new-prefix>` as the run command from "Installed version" with
  `{latest}` in the tag. The image carries skillsaw alone; an install that
  relies on rule plugins takes the `uvx --with` form below instead.

## Declining the upgrade

Do not modify the local installation. Offer an isolated, zero-install
command as `<new-prefix>` instead, such as `uvx skillsaw=={latest}` or the
container run command above, to evaluate the new rules and bump pins. If the
user agrees, continue below with that prefix. If the user also declines
running the new version, retain `<installed-prefix>` as `<new-prefix>`, leave
every pin unchanged (a pin moved to `{latest}` would put CI on rules never
run here), tell the user the update is paused until the new version can run,
and continue below; the router then skips to verification.

## Confirm the new prefix

An isolated command sees only skillsaw itself, so if the installed one
carries rule plugins (packages providing `skillsaw.plugins` entry points,
such as `skillsaw-runbooks`; `pipx list --include-injected`,
`uv tool list --show-with` or `pip list` shows them with their versions), add
each one at the version installed (`uvx --with "<plugin>==<version>"
skillsaw=={latest}`) or the comparison below reports their rules as removed.
A plugin from a path or a private index the isolated command cannot reach
rules the isolated comparison out: say so and take the retained prefix.

If an upgrade or an isolated prefix was accepted, `<new-prefix> --version`
must report `{latest}` (the output is `skillsaw {latest}`). If it does not,
the upgrade did not take; report which manager ran and stop. Then, on every
path, save the new prefix's rules (the already-current path repeats the old
list, so its comparison comes out empty; the paused path writes it and never
compares):

```console
<new-prefix> list-rules > /tmp/skillsaw-rules-new.txt
```

Retain both prefixes and both files, then return to the router.
