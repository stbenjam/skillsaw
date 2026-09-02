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
- Directories loaded as a whole by a script — globbed (`schemas/*.xsd`),
  joined to a base path (`Path(__file__).parent / "schemas"`), or enumerated
  (`os.listdir('data')`, `fs.readdirSync("assets")`)
- Python imports resolved within the skill package

Path join operators and directory-reading calls indicate intentional directory loading; standalone words in configuration settings (like `"workload_manager": "slurm"`) do not match directories.

Never flagged (all case-insensitive): SKILL.md itself, README and
CHANGELOG in any extension, `LICENSE*` and `NOTICE*` files (such as
`LICENSE-MIT` or `license.txt`), test files and scaffolding (`evals/`,
`tests/`, `test_*.py`, and `testdata/`), hidden files or directories,
and symlinks. You can add more patterns using the `exclude` option.

## Consolidating findings for large directories

When a directory contains more unreferenced files than `collapse_directory_threshold` (default: 5), skillsaw groups them into a single friendly finding summarizing the contents:

```
⚠ [my-skill/data]: 12 unreferenced files under 'data/' (a.json, b.json,
  c.json, and 9 more) — unreferenced files add unused bulk and might contain
  unreviewed behavior; reference the directory from SKILL.md, or exclude it
```

This keeps your lint report clean and focused. To report every file individually, set `collapse_directory_threshold: 0`.

Files matched by a global or per-rule `exclude` never count toward the threshold. A baseline written before findings were consolidated lists the files one by one; it keeps suppressing the directory finding until the pile grows, and the next `skillsaw baseline` records the directory instead.

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
