# Documentation / Question / Other — Checklist

Use this for issues that are not a code defect or a feature request:
documentation problems, usage questions, and everything else (duplicate,
invalid, spam, out-of-scope, needs-more-info).

## Documentation

- **Verify the claim.** Confirm the docs are actually wrong, missing, or unclear
  by checking the source: `README.md`, `docs/` (published at `skillsaw.org`),
  and generated rule docs. Distinguish "docs are wrong" from "code is wrong"
  (the latter is a `bug`).
- **Locate it.** Name the exact page/section/file that needs the change.
- **Drift vs. gap.** Is the behavior documented somewhere but stale, or never
  documented? A moved/renamed page also needs an mkdocs-redirects entry so
  existing `skillsaw.org` URLs do not break.
- **Enrich** with the specific file and the corrected/added wording you would
  suggest.

## Question / Support

- **Answer from the code and docs**, not from memory — verify the behavior the
  reporter is asking about and cite where it is defined or documented.
- If the answer reveals a real defect or a genuine gap, reclassify to `bug` or
  `feature` and note that in the comment.
- Link the relevant docs so the reporter can self-serve next time.

## Other (duplicate / invalid / spam / out-of-scope / needs-info)

- **Duplicate**: find and link the original (`gh issue list --search "<keywords>"`);
  recommend closing as duplicate of #N.
- **Needs-info**: list precisely what is missing to make the issue actionable
  (version, config, input file, exact command, observed vs. expected).
- **Out-of-scope**: explain why it is outside skillsaw's job and, when relevant,
  redirect (e.g. a rule plugin, or an upstream tool's tracker).
- **Invalid / spam**: state briefly why and recommend closing.

## Enrichment to add (all sub-types)

- The verified facts and where they live (`file:line`, doc URL, or issue/PR link).
- A concrete recommendation: what to change, answer, link, or close-as.
- Suggested labels (`documentation`, `question`, `duplicate`, `needs-info`, etc.).
