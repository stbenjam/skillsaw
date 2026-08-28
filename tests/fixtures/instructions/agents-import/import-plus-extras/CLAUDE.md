<!-- Shared instructions live in AGENTS.md so every assistant reads one file. -->
@AGENTS.md

## Claude Code specifics

Load the `release` skill before cutting a tag; it walks the changelog and
the version bump in the order this project expects. Slash commands live in
`.claude/commands/` and are not visible to other assistants.
