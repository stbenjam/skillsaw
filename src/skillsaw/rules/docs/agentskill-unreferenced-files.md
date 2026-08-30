## Why

Every file bundled in a skill directory should be reachable from
SKILL.md. An unreferenced file is dead weight in the skill package —
it ships to every consumer, inflates installs, and rots silently
because nothing points at it.

It is also a security risk: unreferenced files can bundle hidden or untrusted
functionality that reviewers skip because the skill instructions never ask
an agent to open or run them.

## What counts as a reference

A file is referenced when its path or filename is mentioned in SKILL.md **or
transitively** in any local file reachable from SKILL.md (e.g. SKILL.md →
`references/a.md` → `references/b.md`). A skill-root `README.md` and
`agents/openai.yaml` also count as reference roots.

Mentions are detected in markdown links, inline code spans, fenced code blocks,
and plain prose:

- Relative paths and bare filenames (`scripts/run.py` or `run.py`)
- Case-insensitive filename matches
- Directory mentions covering their contents (`references/` or `./assets`)
- Python imports resolved within the skill package


Never flagged: SKILL.md itself, README.md, CHANGELOG.md, LICENSE* and
NOTICE* files (any suffix, e.g. `LICENSE-MIT`), files under `evals/`
and `tests/` (eval/test scaffolding is consumed by external harnesses
by convention, not referenced from the skill text), `test_*.py` files
and anything under a `testdata/` directory at any depth (bundled
scripts routinely ship self-tests and fixtures), hidden files or
directories, and symlinks (which are also never followed). The
`exclude` option adds glob patterns on top of these defaults.

## Examples

**Bad:**

```
my-skill/
  SKILL.md          # only mentions scripts/run.py
  scripts/
    run.py
    cleanup.py      # never mentioned anywhere — dead or hidden behavior
```

**Good:**

```
my-skill/
  SKILL.md          # "Run `python scripts/run.py`, then scripts/cleanup.py"
  scripts/
    run.py
    cleanup.py
```

## How to fix

Delete the unreferenced file, or mention it from SKILL.md (or from a
markdown file SKILL.md references) so agents and reviewers know why it
is bundled. If the file is intentionally unlisted supporting data,
either mention its directory (`assets/`) from SKILL.md or add a glob
to the rule's `exclude` option:

```yaml
rules:
  agentskill-unreferenced-files:
    exclude:
      - "assets/fonts/*"
```
