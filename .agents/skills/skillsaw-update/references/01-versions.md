# Resolve versions and upgrade

Record the installed version first; nothing below upgrades until the old
rule list is captured in the next section.

## Installed version

Run `skillsaw --version`. If it works, retain that command prefix and note
the version as `{installed}`.

Otherwise the repository is not on a working install yet: prefer zero-install
execution with `uvx skillsaw`, then `pip install skillsaw`, then the
installed container runtime (`podman` or `docker`). Verify with `--version`
and treat that version as both `{installed}` and the starting prefix.

## Latest version

Resolve the newest release to `{latest}`:

```console
python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('https://pypi.org/pypi/skillsaw/json'))['info']['version'])"
```

If PyPI is unreachable:

```console
git ls-remote --tags https://github.com/stbenjam/skillsaw.git 'v*' | sort -t/ -k3 -V | tail -1
```

Strip the leading `v` from the tag for the `{latest}` version number.

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
- **pip**: `pip install "skillsaw=={latest}"`.
- **Container**: pull the pinned image,
  `podman pull ghcr.io/stbenjam/skillsaw:v{latest}`
  (or `docker pull ...`). A `:latest` tag floats and needs no pull to
  float, but prefer the pinned `v{latest}` tag for repeatability.

Verify the new prefix with `<new-prefix> --version` and save its rules:

```console
<new-prefix> list-rules > /tmp/skillsaw-rules-new.txt
```

Retain both prefixes and both files, then return to the router.
