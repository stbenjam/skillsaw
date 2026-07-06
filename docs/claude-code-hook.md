# Claude Code Hook

The skillsaw [Claude Code plugin](plugins.md) ships a `PostToolUse` hook that
lints agent context **as it's written**. When Claude edits a `SKILL.md`,
`CLAUDE.md`, plugin manifest, or any other file skillsaw understands, the hook
lints that file immediately and feeds any violations back to the agent — so
they get fixed in the same turn, long before CI or a commit.

Where the [Pre-commit](pre-commit.md) hook is a gate on a finished commit, this
is live feedback on a single edit.

## Setup

Install the skillsaw plugin from its marketplace, then make sure the `skillsaw`
CLI is on your `PATH`:

```bash
pipx install skillsaw   # or: pip install skillsaw
```

That's it. The hook is wired up in the plugin's `hooks/hooks.json` and runs
automatically. If the `skillsaw` command isn't installed, the hook is a no-op —
it never breaks editing.

## How it works

The hook fires only on file-editing tool calls (`Edit`, `Write`, `MultiEdit`,
`Update`). On each, it:

1. Checks whether the edited file is one skillsaw lints (`SKILL.md`,
   `CLAUDE.md`, `AGENTS.md`, plugin/marketplace manifests, `hooks.json`,
   `settings.json`, `.mcp.json`, Cursor `.mdc` rules, and command/agent/rule
   bodies). Anything else — source code, docs, config — is ignored instantly.
2. Lints that one file using the repository's own `.skillsaw.yaml`, then
   reports **only** the violations that land on the file just edited, never its
   siblings.
3. If there are violations at (or above) the repository's configured `fail-on`
   severity, prints them for the agent and exits `2`, which Claude Code surfaces
   as feedback. Otherwise it stays silent.

The edit itself is never undone — this is advisory feedback, not a gate.

## Configuration

The hook takes no configuration of its own. It honors your repository's
`.skillsaw.yaml` exactly like a manual `skillsaw lint` run: the same enabled
rules, severities, excludes, inline suppressions, and baseline. In particular:

- **`fail-on` sets the bar.** A repo that only fails on errors hears only about
  errors; one running `strict`/`fail-on: warning` hears about warnings too. If
  the bar is lenient, the hook is quiet — matching feedback to the threshold you
  chose keeps it from becoming noise.
- **The baseline is respected.** Pre-existing violations recorded in a
  [baseline](baseline.md) are suppressed, so the agent only hears about problems
  its own edit introduced.

## Running skillsaw by hand from a hook

The hook is a thin wrapper around a dedicated subcommand:

```bash
skillsaw hook post-tool-use
```

It reads the Claude Code tool-call payload as JSON on stdin and lints the edited
file. You won't normally invoke it yourself — it exists so the plugin's
`hooks/hooks.json` has something to call — but it's a plain CLI command you can
test with a crafted payload:

```bash
echo '{"tool_name":"Edit","tool_input":{"file_path":"path/to/SKILL.md"}}' \
  | skillsaw hook post-tool-use
```
