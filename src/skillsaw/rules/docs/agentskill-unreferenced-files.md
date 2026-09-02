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
- Directories a bundled script loads as a whole — globbed
  (`schemas/*.xsd`), joined onto a base path
  (`Path(__file__).parent / "schemas"`), or enumerated
  (`os.listdir('data')`, `fs.readdirSync("assets")`)
- Python imports resolved within the skill package

The join operator and the call name are what turn a bare word into a
path: a quoted word on its own is not one, so a config value such as
`"workload_manager": "slurm"` never covers a `slurm/` directory.

Never flagged (all case-insensitive): SKILL.md itself, README and
CHANGELOG in any extension, LICENSE* and NOTICE* files (any suffix, so
both `LICENSE-MIT` and `license.txt`), files under `evals/` and
`tests/` (eval/test scaffolding is consumed by external harnesses by
convention, not referenced from the skill text), `test_*.py` files and
anything under a `testdata/` directory at any depth (bundled scripts
routinely ship self-tests and fixtures), hidden files or directories,
and symlinks (which are also never followed). The `exclude` option adds
glob patterns on top of these defaults.

## One finding per directory full of dead files

More than `collapse_directory_threshold` (default 5) unreferenced files
in one directory report as a single finding that names the directory
and samples its contents:

```
⚠ [my-skill/data]: 12 unreferenced files under 'data/' (a.json, b.json,
  c.json, and 9 more) — dead weight that can hide unreviewed behavior;
  reference the directory from SKILL.md, or exclude it
```

A vendored schema tree is one decision for the author, not twelve, and
one finding per file buries every other finding in the run. Set the
option to `0` to report every file individually.

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

**Also good** — the script loads the directory, so its contents are not dead:

```
my-skill/
  SKILL.md          # "Run `python scripts/validate.py doc.docx`"
  scripts/
    validate.py     # SCHEMAS = Path(__file__).parent / "schemas"
    schemas/
      wml.xsd
      sml.xsd
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

A finding that names a directory rather than a file is asking the same
question about the whole directory: reference it, delete it, or exclude
it.
