# Build the corpus

## Clone the shared corpus

Shallow-clone into `~/tmp/skillsaw-audit/corpus/<owner>_<repo>/` with
`git clone --depth 1`, in a background script, before launching any agent.
One shared corpus keeps every reviewer's numbers comparable.

## Search for each new rule's file type

Start from the reference collection and the largest marketplace for every
ecosystem skillsaw supports, then add whatever `gh search code` finds for
each new rule's file type — at least ten distinct repositories per rule:

```bash
gh search code --extension md "agent.md" path:.github/agents
gh search code filename:server.json "io.modelcontextprotocol.registry"
gh search code filename:skills-lock.json
gh search code path:.devin/rules
```

A dedicated reviewer will add more for its own rule; that is expected. Tell
every agent the corpus path and that a clone failure for a guessed repository
name is normal.

## Install the last release

For differential runs, install the last release into its own venv:

```bash
uv venv ~/tmp/skillsaw-audit/venv-<last>
uv pip install --python ~/tmp/skillsaw-audit/venv-<last>/bin/python skillsaw==<last>
```

Compare per-rule counts with `--format json -v --fail-on info --no-baseline`
on both versions. Every finding that appears only in the new version on an
unchanged file is a candidate false positive; every finding that disappears
is a candidate false negative or an intended fix.
