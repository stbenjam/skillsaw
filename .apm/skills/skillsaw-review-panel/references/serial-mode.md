# Serial Mode — Execution

Read this only when `--serial` is passed, or when the Agent tool is
unavailable and parallel dispatch has fallen back to serial. The default
path never loads it.

Run all 7 specialists **inline in the main agent**, one after
another. Do **not** launch sub-agents.

For each specialist in roster order (Architecture, Python Expert,
Security & Supply Chain, QA Engineer, Technical Writer, Ecosystem,
Palimpsest):

1. Write the specialist name as a heading.
2. **Read that specialist's `references/*.md` file now** — read the
   detailed scope it holds. Do not review from the one-line lens alone.
3. Review the diff and repo through that specialist's lens. Read files,
   grep, and run git commands to gather evidence — context from earlier
   specialists' file reads carries over.
4. Write findings in the format above.
5. If no issues found, say so and list what was checked.
6. Move on to the next specialist.
