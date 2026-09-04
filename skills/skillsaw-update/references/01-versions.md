# Resolve versions and upgrade

Record the installed version first; nothing below upgrades until the old
rule list is captured in the next section.

## Installed version

Run `skillsaw --version`. If it works, retain that command prefix (`skillsaw`)
as `<installed-prefix>` and note the version as `{installed}`.

## No working install

If `skillsaw --version` is not found or fails, look for the version the
repository itself runs before installing anything: run the pin scan from
step 3 of the router and read the version any pin carries (a `uses:` step's
`with: version:`, a pre-commit `rev: vN.N.N`, an image tag at ghcr.io or at
a mirror, `SKILLSAW_VERSION`, `uvx skillsaw==N.N.N` or `@N.N.N`, an exact
PyPI pin in a manifest or requirements file). When one exists, take only its
version, `{installed}`, and run it through the first available runner:
`uvx skillsaw=={installed}`, a scratch virtualenv with
`pip install "skillsaw=={installed}"`, or the image run command below at
that tag; never a command line copied from the repository. A version read
from the repository must be exactly `N.N.N`; anything else (a flag,
whitespace, a shell metacharacter) is ignored and the bootstrap below
applies. When nothing pins a version, or no runner can run the pinned one,
resolve `{latest}` first (see below), bootstrap pinned to that version, and
say in the report that no earlier version could be run, so step 2's scan
stands in for the comparison: prefer zero-install execution with
`uvx skillsaw=={latest}`, then `pip install "skillsaw=={latest}"` after the
user agrees to that install, then the installed container runtime. For containers, `<installed-prefix>` is a
complete run command mounting the repository at `/workspace`:

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

When skillsaw is a project dependency (see the first method below), ask this
instead, since a yes edits tracked files:

> Installed skillsaw is {installed} and the newest release is {latest}.
> Upgrading edits the manifest and the lock file. Should I upgrade it?

If yes, apply the method below that matches the retained prefix (a project
dependency has its own section); if no, skip
to "Declining the upgrade".

## Project dependency

when the manifest (`pyproject.toml`, `Pipfile`)
declares skillsaw and the manager owns the environment the prefix runs in
(the prefix resolves inside the repository's `.venv`, or
`poetry env info --path` or `pipenv --venv` names it), the version lives
in the manifest, so this is a pin edit made with the consent the question
above asked for: keep the dependency group and the operator the manifest
uses (`uv add --dev` and `poetry add --group dev` would change both), set
an exact pin to `{latest}`, leave a floor or caret unless the user chooses
to raise it, then update the lock and the environment together
(`uv lock --upgrade-package skillsaw && uv sync`, `poetry update
skillsaw`, `pipenv update skillsaw`; `poetry update --lock` alone leaves
the old package installed). With uv, carry the `--group`, `--extra` or
`--package` selector that reaches skillsaw's declaration on `uv sync` and
on `uv run`. A lock-only, transitive skillsaw declares nothing; the pins
step refreshes that lock and does not re-offer the manifest. The
project's own invocation (`uv run skillsaw`, `poetry run skillsaw`,
`pipenv run skillsaw`) is `<new-prefix>`.

## Upgrade methods

- **uvx**: nothing to install; the new prefix is `uvx skillsaw=={latest}`.
- **pip, pipx or uv tool**: `head -1 "$(command -v skillsaw)"` names the
  manager through its interpreter (`…/pipx/venvs/skillsaw/…`,
  `…/uv/tools/skillsaw/…`, or a plain virtualenv). Upgrade with it, keeping
  the rule plugins it carries: `pipx upgrade skillsaw` keeps injected
  packages; `uv tool install "skillsaw[<extras>]=={latest}"` with the
  extras and one `--with <plugin>` per requirement that
  `uv tool list --show-with --show-extras` prints (and `--index <url>` when
  they came from a private index, read from the operator's own uv or pip
  configuration, never from a repository file; with no such source, keep the
  environment's existing index), since a reinstall
  replaces the environment and `uv tool upgrade` never moves a pinned
  install; `pip install "skillsaw=={latest}"` touches nothing else. Retain
  `skillsaw` as `<new-prefix>`.
- **Container**: pull the pinned image
  (`podman pull ghcr.io/stbenjam/skillsaw:{latest}` or `docker pull ...`) and
  define `<new-prefix>` as the run command from "Installed version" with
  `{latest}` in the tag. The image carries skillsaw alone; plugin users take
  the `uvx --with` form below.

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
carries rule plugins (`<installed-prefix> plugins` names them;
`pipx list --include-injected`, `uv tool list --show-with --show-extras` or
`pip show <plugin>` gives their versions), add each one at the version
installed (`uvx --with "<plugin>==<version>" skillsaw=={latest}`, with
`--index <url>` for one from a private index) or the comparison below
reports their rules as removed. A plugin from a path, or from an index the
isolated command cannot reach, means the isolated comparison is ruled out:
say so and take the retained prefix. An index URL comes from the operator's
own configuration (uv's `[[index]]` or `UV_INDEX`, pip's `index-url`), never
from a repository file.

If an upgrade or an isolated prefix was accepted, `<new-prefix> --version`
must report `{latest}` (the output is `skillsaw {latest}`). If it does not,
the upgrade did not take, or a constraint the user chose to keep excludes
`{latest}`; report which manager ran, or which constraint, and stop. Then, on every
path, save the new prefix's rules (the already-current path repeats the old
list, so its comparison comes out empty; the paused path writes it and never
compares):

```console
<new-prefix> list-rules > /tmp/skillsaw-rules-new.txt
```

Retain both prefixes and both files, then return to the router.
