## Why

Every file bundled in a skill directory should be reachable from
SKILL.md. An unreferenced file is dead weight in the skill package —
it ships to every consumer, inflates installs, and rots silently
because nothing points at it.

It is also a security smell: research on malicious skills found that
most hide their behavior in bundled files SKILL.md never mentions
(shadow functionality — OWASP Agentic Skills Top 10, AST01). A script
that no instruction references has no legitimate reason to be in the
package, and reviewers routinely skip files the skill text never asks
an agent to open or run.

## What counts as a reference

A file is referenced when its path or filename is mentioned in
SKILL.md **or transitively** in any local file reachable from SKILL.md
(SKILL.md → `references/a.md` → `references/b.md` counts). Every
referenced file — scripts and data files included, not just markdown —
becomes a reference source: a data file read by a script that SKILL.md
documents (SKILL.md → `check.py` → `allowed-repos.txt`) is covered,
because the whole chain is reviewable. Non-markdown sources contribute
plain-text mentions only (link syntax is resolved only in markdown);
binary files and files over 1 MiB never become sources. A skill-root
README.md also counts as a reference root — a file documented in the
skill's README is neither dead weight nor hidden from review.

Mentions are detected in markdown links, inline code spans, fenced
code blocks (`python scripts/run.py`), and plain prose:

- Relative paths count: `scripts/run.py`, `./scripts/run.py`, or
  `img/logo.png` from a file in the same directory.
- Bare filenames count: a mention of `run.py` anywhere marks
  `scripts/run.py` as referenced. Skills routinely refer to bundled
  scripts by name alone, so requiring full paths would flag
  heavily-referenced files.
- Directory mentions cover their contents (configurable): "read the
  files in `references/`" marks everything under `references/` as
  referenced. Prose and code mentions need the trailing slash; links
  may target the bare directory.

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
