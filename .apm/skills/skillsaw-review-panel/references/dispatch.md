# Step 3 — Specialist dispatch details

**Sub-agents and serial reviewers MUST NOT modify any files, and
MUST NOT run remote-write git commands** (`git push`, force-push
variants, push to protected branches, or pushes to any remote).
They are read-only reviewers.

## Findings format

Each specialist must produce findings in this format:

- **Severity**: `BLOCKING` | `SUGGESTION` | `NOTE`
- **File:line** — include the reference when applicable
- **Finding** — write a description
- **Recommended action** — make it explicit

If no issues found, say so and list what was checked.

**Follow this severity calibration:**
- `BLOCKING`: Correctness regressions, security vulnerabilities,
  architectural faults that compound, or (for the Ecosystem Reviewer) a scope
  violation that warrants redirect-to-plugin. Always include explicit rationale.
- `SUGGESTION`: Substantive feedback that improves the code but is not a
  correctness issue. Keep this the default for real feedback.
- `NOTE`: One-line polish, style nits, minor improvements.

## Prompt path resolution

Resolve specialist scope files from the skill directory:
`.apm/skills/skillsaw-review-panel/references/{specialist}.md`.
Prefer that path over a bare `references/...` path — sub-agents
may not share the skill's working directory.

## Parallel mode (default)

Launch **all 6 specialist sub-agents in a single message** so they
run concurrently, using the Agent tool with `run_in_background: true`.

Each sub-agent gets:
- The specialist role name and a one-line description of its lens
- Instructions to read
  `.apm/skills/skillsaw-review-panel/references/{specialist}.md`
  for its detailed review scope
- The merge base ref and the command to read the diff
  (`git diff <base-ref>...HEAD`)
- The PR number or branch name being reviewed
- Any prior review findings (if detected in Step 2)
- The findings format above
- The read-only contract: must not modify files or push to remotes

Sub-agents have full read access to the locally checked-out
codebase. They explore the code on their own — read files, grep,
and run git commands. Each specialist runs independently and cannot
see the others' output.

Use `subagent_type: "general-purpose"`. Do NOT set the `model`
parameter.

Wait for all sub-agents to complete before proceeding to the
Completeness Gate (Step 4).

## Serial mode (`--serial`)

Run all 6 specialists **inline in the main agent**, one after
another. Do **not** launch sub-agents.

For each specialist in roster order (Architecture, Python Expert,
Security & Supply Chain, QA Engineer, Technical Writer, Ecosystem):

1. Write the specialist name as a heading.
2. **Read that specialist's `references/*.md` file now** — read the
   detailed scope it holds. Do not review from the one-line lens alone.
3. Review the diff and repo through that specialist's lens. Read files,
   grep, and run git commands to gather evidence — context from earlier
   specialists' file reads carries over.
4. Write findings in the format above.
5. If no issues found, say so and list what was checked.
6. Move on to the next specialist.
