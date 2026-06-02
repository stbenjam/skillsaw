# Other Coding Agents

skillsaw works with any AI coding agent, not just Claude Code. If your agent
can read URLs or install packages, you can onboard your repository to skillsaw
in a single prompt.

## One-Prompt Onboarding

The easiest way to get started is to tell your coding agent to read and follow
the onboarding skill directly from GitHub:

```
Read and follow the instructions in
https://raw.githubusercontent.com/stbenjam/skillsaw/refs/heads/main/skills/skillsaw-onboard/SKILL.md
to onboard this repo to skillsaw.
```

The onboarding skill walks the agent through installing skillsaw, running the
initial scan, applying autofixes, setting up CI, and creating a baseline — all
in one pass.

## Installing skillsaw as a Skill

Most coding agents support installing skills or tools from URLs. Consult your
agent's documentation for the exact syntax, then point it at the onboarding
skill:

| Agent | Example |
|-------|---------|
| Claude Code | `skillsaw-onboard` is available as a [plugin](https://docs.claude.com/en/docs/claude-code/plugins-reference) |
| Cursor | Add the SKILL.md URL to your rules or instructions |
| Copilot | Reference the SKILL.md URL in your agent instructions |
| Other | Paste the raw URL into your agent's prompt or context |

## Manual Setup

If your agent doesn't support reading URLs, you can install skillsaw and run
it directly:

```bash
# Install
pip install skillsaw
# or: uvx skillsaw

# Scan your repo
skillsaw tree
skillsaw

# Apply safe fixes
skillsaw fix

# Accept remaining violations as baseline
skillsaw baseline

# Set up config
skillsaw init
```

Then tell your agent about skillsaw in its instruction file (AGENTS.md,
.cursor/rules, etc.):

```markdown
## Linting

This repo uses [skillsaw](https://skillsaw.org) to lint instruction files,
skills, and plugins. Run `skillsaw` before committing changes to instruction
files and fix any violations.
```

## What the Onboarding Skill Does

The onboarding skill performs these steps automatically:

1. **Install** — detects the best installation method (uvx, pip, or container)
2. **Scan** — runs `skillsaw tree` and `skillsaw` to assess current state
3. **Autofix** — runs `skillsaw fix` for deterministic fixes (frontmatter,
   naming, registration)
4. **Manual fix** — edits remaining violations directly (weak language,
   tautological statements, structural issues)
5. **Baseline** — snapshots any remaining violations so only new ones fail
6. **Configure** — generates `.skillsaw.yaml` if missing
7. **CI** — offers to set up GitHub Actions or GitLab CI
8. **Makefile** — optionally adds `lint` and `lint-fix` targets
9. **Verify** — runs a final lint pass and summarizes all changes
