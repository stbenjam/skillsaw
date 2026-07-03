# Pre-commit

skillsaw ships a [Pre-commit](https://pre-commit.com/) hook so every
contributor to your repository runs the linter on commit, at a pinned
version, with no install instructions.

## Setup

Add skillsaw to your repository's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/stbenjam/skillsaw
    rev: v0.15.0
    hooks:
      - id: skillsaw
```

Then install the git hook once per clone:

```bash
pre-commit install
```

From now on, any commit that touches a file skillsaw lints — `CLAUDE.md`,
`SKILL.md`, plugin manifests, `hooks.json`, promptfoo configs, and the rest —
runs the linter first. Violations at error severity (or warnings, with
`strict: true` in `.skillsaw.yaml`) block the commit. Commits that touch
nothing relevant skip the hook entirely.

You can also run it on demand across the whole repository:

```bash
pre-commit run skillsaw --all-files
```

## How the hook works

Most Pre-commit hooks receive the list of staged filenames and lint each file
independently. skillsaw is a **repo-level** linter: it detects your repository
type, validates marketplace registration, and runs cross-file rules, none of
which map to per-file invocation. The hook therefore declares
`pass_filenames: false` and lints the whole repository.

The hook's `files` pattern only controls *when* it fires — at least one staged
file must match it. The pattern covers everything skillsaw discovery looks at:
instruction files (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `*.instructions.md`),
skills (`SKILL.md`), plugin and marketplace manifests (`.claude-plugin/`),
`.claude/` directories, hooks, MCP and settings JSON, Cursor/Copilot/Kiro/APM
formats, CodeRabbit and promptfoo configs, and skillsaw's own config and
baseline files.

Because the whole repository is linted, a pre-existing violation in a file you
didn't touch can block your commit. If you're adopting skillsaw on a repo with
existing violations, [create a baseline](baseline.md) first — baselined
violations don't fail the lint, so the hook only flags new problems.

## Pinning

The `rev:` field pins the skillsaw version. Git tags are mutable; if your
threat model includes a compromised upstream re-pointing a tag, pin a full
commit SHA instead:

```yaml
  - repo: https://github.com/stbenjam/skillsaw
    rev: 3e1188f446413e6d6818c98644d2d6a84e4038e7  # v0.14.1
    hooks:
      - id: skillsaw
```

`pre-commit autoupdate` bumps `rev:` to the latest tag as an explicit,
reviewable diff. See [Supply Chain Protection](supply-chain-protection.md) for
the broader trust model, including the release attestations that let you
verify what you're pinning.

## Configuration

The hook needs no configuration of its own — it respects your repository's
`.skillsaw.yaml` exactly like a manual `skillsaw lint` run, including rule
overrides, excludes, `strict` mode, inline suppressions, and the baseline.

To pass extra CLI flags, override `args` in your config:

```yaml
    hooks:
      - id: skillsaw
        args: [--skip-rule, content-weak-language]
```

## Troubleshooting

**The hook runs on commits I didn't expect.** The `files` pattern is broad by
design (it includes top-level `commands/`, `skills/`, `agents/`, `hooks/`, and
`rules/` directories, which plugin-style repos use). If your repository uses
one of those directory names for something unrelated, narrow the trigger in
your own config:

```yaml
    hooks:
      - id: skillsaw
        files: ^(CLAUDE\.md|\.claude/|\.claude-plugin/)
```

**The hook fails on files I didn't change.** That's the repo-level lint
working as intended — see the baseline note above.

**Environment is stale after a skillsaw release.** Pre-commit caches the hook
environment per `rev`. Run `pre-commit autoupdate` to move to a new release,
or `pre-commit clean` to rebuild environments.
