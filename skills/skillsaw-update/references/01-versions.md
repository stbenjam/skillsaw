# Resolve versions and upgrade

Record the installed version first; nothing below upgrades until the old
rule list is captured in the next section.

## Installed version

Run `skillsaw --version`. If it works, retain that command prefix (`skillsaw`)
and note the version as `{installed}`.

If `skillsaw --version` is not found or fails, the repository is not on a
working install yet. Resolve `{latest}` first (see below), then bootstrap
pinned to that version: prefer zero-install execution with
`uvx skillsaw=={latest}`, then `pip install "skillsaw=={latest}"`, then the
installed container runtime. For containers, define `{installed-prefix}` as a
complete run command mounting the repository at `/workspace`:

```console
podman run --rm -v "$PWD:/workspace" ghcr.io/stbenjam/skillsaw:v{latest}
```

(or `docker run --rm -v "$PWD:/workspace" ghcr.io/stbenjam/skillsaw:v{latest}`).
Verify with `<installed-prefix> --version` and treat that version as both
`{installed}` and the starting prefix.

## Latest version

Resolve the newest release to `{latest}`:

```console
python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/skillsaw/json'))['info']['version'])"
```

If PyPI is unreachable:

```console
git -c 'versionsort.suffix=-' ls-remote --tags --sort='v:refname' https://github.com/stbenjam/skillsaw.git 'v*' | tail -1
```

Strip the leading `v` (and any trailing `^{}`) from the tag for the `{latest}`
version number.

If `{installed}` equals `{latest}`, report that the install is current and
continue: there are no new rules, but pins may still lag behind.

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

If yes, follow the method behind the retained prefix:

- **uvx**: nothing to install. The new prefix is
  `uvx skillsaw=={latest}`; the old one stays usable for comparison.
- **pip**: run `pip install "skillsaw=={latest}"` and retain `skillsaw` as
  `<new-prefix>`.
- **Container**: pull the pinned image
  (`podman pull ghcr.io/stbenjam/skillsaw:v{latest}` or `docker pull ...`)
  and define `<new-prefix>` as
  `podman run --rm -v "$PWD:/workspace" ghcr.io/stbenjam/skillsaw:v{latest}`
  (or `docker run ...`).
- **Local binary (`skillsaw`)**: upgrade via `pip install --upgrade "skillsaw=={latest}"`
  or the project's package manager, retaining `skillsaw` as `<new-prefix>`.

If no:
Do not modify the local installation. Offer to select an isolated, zero-install
command as `<new-prefix>` (such as `uvx skillsaw=={latest}` or
`podman run --rm -v "$PWD:/workspace" ghcr.io/stbenjam/skillsaw:v{latest}`) to
evaluate new rules and bump version pins without modifying local packages.
If the user agrees, use that prefix for `<new-prefix>` and continue below;
if the user also declines running the new version, stop the update workflow
immediately.

Verify the new prefix with `<new-prefix> --version` and save its rules:

```console
<new-prefix> list-rules > /tmp/skillsaw-rules-new.txt
```

Retain both prefixes and both files, then return to the router.
