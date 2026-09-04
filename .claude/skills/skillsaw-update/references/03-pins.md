# Update version pins

Change only pins that reference skillsaw; leave third-party actions and
unrelated tooling untouched. `{old}` below is the version a pin currently
carries, which may differ from `{installed}`. Search with
`git grep --untracked`, as the router does: ignored build output stays out
while a pin in a file not yet added still counts. A tracked vendored or
generated tree is searched like any other; the judgment two sentences on
filters it. Pathspec lists name a file both bare and under `**/`, because
the `**/` form matches only below a directory. Outside a git work tree, use
`grep -rn --exclude-dir={.git,.venv,node_modules,vendor,dist,site}` (brace
expansion; list them separately in a shell without it), with
`--include=<name>` for each pathspec a recipe lists. A search finds more than
the repository executes: edit only pins CI or local tooling runs, skip
documentation, examples, templates shipped to others and test fixtures, and
list those as found, not changed. A floating `@v0` action ref is a deliberate
pinning strategy; convert it to a SHA only after the user agrees. A bot may
already own some pins: each `package-ecosystem:` entry in
`.github/dependabot.yml` names a surface it covers (`github-actions`, `pip`,
`uv`, `docker` for Dockerfiles but not Containerfiles, `pre-commit`), and
Renovate (`renovate.json*`, `.renovaterc*`, `.github/renovate.json*`,
`.gitlab/renovate.json*`) covers actions, Dockerfiles, GitLab CI and PyPI by
default but pre-commit only when its `pre-commit` manager is enabled. A bot
entry covers only the `directory:` it names and what its filters admit
(Renovate can disable a manager, ignore paths or exclude skillsaw through
package rules), so a pin outside that is uncovered, and uncertain coverage
means the pin is offered. Offer to bump only what no bot covers (action
`version:` inputs and defaults, `SKILLSAW_VERSION`, mirrored registry paths)
unless the user wants them all now. Track each edited file for the final
summary.

## GitHub Actions and action definitions

Find every workflow and action definition referencing skillsaw:

```console
git grep --untracked -nE -A6 "stbenjam/skillsaw(@|/review@)" -- '*.yml' '*.yaml'
```

This covers both the lint action (`stbenjam/skillsaw@<SHA>`) and the review
action (`stbenjam/skillsaw/review@<SHA>`), in `.yml` and `.yaml` workflows
and in action metadata alike; the trailing context shows a `with: version:`
input under the step, which the `uses:` line alone does not. When a step's
`with:` block runs past the context, read the whole step in the file.

Resolve the commit SHA of the newest release tag before editing:

```console
git ls-remote https://github.com/stbenjam/skillsaw.git 'refs/tags/v{latest}' 'refs/tags/v{latest}^{}'
```

An annotated tag yields two lines; use the SHA on the `^{}` line, which is
the commit the tag points to. A lightweight tag yields one line, and its SHA
is the commit. The result must be a 40-character hex SHA; if the command
prints nothing, the tag is not pushed yet, so stop and report it, and never
write a SHA you did not read from this output. Replace the old SHA in each
`uses:` line the repository runs and refresh the trailing version comment to
`# v{latest}`; a `uses:` ref that is an exact tag (`@v{old}`) is an exact pin
too, and moves to `@v{latest}` in place:

```yaml
- uses: stbenjam/skillsaw@<NEW_SHA> # v{latest}
```

Or for the review action:

```yaml
- uses: stbenjam/skillsaw/review@<NEW_SHA> # v{latest}
```

A step that also passes `with: version: {old}` to the action gets `{latest}`
there too. When that input is an expression (`${{ vars.SKILLSAW_VERSION }}`,
`${{ env.SKILLSAW_VERSION }}`), update the variable it reads, not the
expression.

If the repository defines its own actions, find the skillsaw version input in
each action metadata file and its default, whatever the quoting:

```console
git grep --untracked -n -iA8 skillsaw -- 'action.yml' 'action.yaml' '**/action.yml' '**/action.yaml' | grep -E 'default: *["'"'"']?v?[0-9]'
```

Update that input's default from `{old}` to `{latest}`, keeping the quoting
and `v` prefix the file already uses; leave other inputs' defaults alone.

## Makefile targets

Find the pinned version:

```console
git grep --untracked -n "SKILLSAW_VERSION" -- Makefile GNUmakefile makefile '**/Makefile' '**/GNUmakefile' '**/makefile' '*.mk'
```

Update the version value while preserving the existing assignment operator
(`SKILLSAW_VERSION := {latest}` or `SKILLSAW_VERSION ?= {latest}`). When the
targets run through a container, the image tag below it references the same
variable (`ghcr.io/stbenjam/skillsaw:$(SKILLSAW_VERSION)`), so one edit covers
both. Never overwrite existing `lint` or `lint-fix` target bodies; only the
version assignment changes.

## Pre-commit hooks

Find the skillsaw entry:

```console
git grep --untracked -n -B3 -A3 "stbenjam/skillsaw" -- '.pre-commit-config.yaml' '**/.pre-commit-config.yaml'
```

The entry looks like this:

```yaml
repos:
  - repo: https://github.com/stbenjam/skillsaw
    rev: v{latest}
    hooks:
      - id: skillsaw
```

Set `rev:` to the `v{latest}` tag; git tags do carry the `v`. On a tag-form
`rev:`, `pre-commit autoupdate --repo https://github.com/stbenjam/skillsaw`
does it for you; confirm the resulting `rev:` reads `v{latest}`, since a tag
not yet pushed leaves it behind. When the project pins `rev:` to a commit SHA
instead, resolve `v{latest}` the way the Actions section does and use that
SHA, or run the same
command with `--freeze`, which keeps the pin a SHA and writes the
`# frozen: v{latest}` comment; plain `autoupdate` would rewrite it to a
mutable tag. Refresh any trailing `# v{old}` comment either way.

## Container image tags and Dockerfiles

Find every image reference, including nested Dockerfiles, Containerfiles and
GitLab CI configurations:

```console
git grep --untracked -nE 'stbenjam/skillsaw(:|@sha256:|[[:space:]]|"|'"'"'|$)'
```

The suffix form finds `ghcr.io/stbenjam/skillsaw` and a mirrored path such as
`registry.example.com/mirror/stbenjam/skillsaw` alike, an untagged reference
included, while `uses:` action refs (`@<SHA>`) stay out. Retag `:{old}` to
`:{latest}` where the repository runs the image: Dockerfiles, Containerfiles,
`.gitlab-ci.yml` and any GitLab CI file it includes, any other CI file that
names the image (CircleCI, Azure Pipelines, Tekton), and a mirrored path the
same way. Image tags carry no `v`. A digest pin (`:{old}@sha256:…`, or a
digest alone) needs the new tag's digest, read from the registry the pin
names: `skopeo inspect --format '{{.Digest}}' docker://<pinned path>:{latest}`,
`crane digest <pinned path>:{latest}` or
`docker buildx imagetools inspect <pinned path>:{latest}` prints it;
retagging around a stale digest changes nothing. With none of those tools at
hand, leaving the digest pin as it is and reporting it is the safe default;
drop the digest only if the user prefers, and say in the summary that the
pin is now a mutable tag. When the tag is indirect (`:$(SKILLSAW_VERSION)`,
`:${SKILLSAW_VERSION}`, or a `FROM` built from an `ARG`), update the variable
or build argument it reads instead. A `:latest` tag, or an untagged reference,
which means the same, floats onto the new release by itself; recommend pinning
it to `:{latest}` for repeatable pipelines, but only change it after the user
agrees.

## PyPI pins

Find pip-style pins in requirements files, `pyproject.toml`, `tox.ini`,
Dockerfiles and CI configurations, in PEP 508 spacing, with extras, with a
`$VAR` in place of the version, and as a direct reference
(`skillsaw @ git+https://github.com/stbenjam/skillsaw.git@v0.19.0`):

```console
git grep --untracked -nE '(^|[^/[:alnum:]._-])skillsaw *(\[[^]]*\])? *(={1,3}|~=|>=?|<=?|!=|@) *([0-9]|\$|git\+|https?://)'
```

Then the mapping forms `pyproject.toml` tools write (`skillsaw = "^0.19.0"`,
`skillsaw = '^0.19.0'`, `skillsaw = { version = "0.19.0" }`):

```console
git grep --untracked -nE '^[[:space:]]*skillsaw[[:space:]]*=[[:space:]]*[{"'"'"']'
```

The leading boundary keeps `acme-skillsaw`, `python_skillsaw` and
`stbenjam/skillsaw@<SHA>` action refs out. Bump an exact pin (`==`, `===`,
uvx's `skillsaw@N.N.N`) the repository installs to `{latest}`, and move a
direct reference's `@v{old}` ref to `v{latest}`. A floor (`>=`, `~=`, a
caret) that `{latest}` already satisfies stays as it is unless the user
chooses to require the new version; a cap (`<`, `<=`) or an exclusion (`!=`)
is likewise a deliberate constraint: report it as found and change it only
after the user agrees, a cap raised just far enough to admit `{latest}` and
an exclusion left alone, since it bars a release rather than selecting one.
A `$VAR`-indirect pin is updated where the variable is defined, the way the
container section does. Never hand-edit a lockfile (`uv.lock`,
`poetry.lock`, `Pipfile.lock`, a pip-tools `requirements.txt`): regenerate
the one package (`uv lock --upgrade-package skillsaw`,
`poetry update --lock skillsaw`, `pipenv update skillsaw`,
`pip-compile --upgrade-package skillsaw`) and report it as edited. A
lockfile can be the only place skillsaw is pinned; this finds the entry
(`git grep --untracked -n 'name = "skillsaw"' -- '*.lock'` finds it), and
the lock is regenerated the same way.

Return to the router with the list of edited files.
