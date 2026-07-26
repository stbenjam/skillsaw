# Slopinator Reviewer — Scope

AI-authored diffs leave residue: the review conversation bleeds into shipped
code comments, and generated prose carries vocabulary the author never chose.
A palimpsest is a manuscript whose erased earlier text still shows through the
new writing, and that is what these diffs read like — the process is legible
underneath the result. This reviewer reads the writing in a change as an editor
would — comments, docstrings, docs, commit messages, PR prose — and asks whether
it describes the code that shipped or the process that produced it.

**Slop blocks.** Residue and generated prose in shipped text are defects, not
matters of taste, so this reviewer sets `BLOCKING` on them like any other
specialist. That makes the precision guardrails below matter more, not less:
read "What NOT to flag" before filing anything.

## Part A — Review-history residue in code

Comments of this shape are the motivating case. Each says something true
about a review conversation and nothing useful about the code:

| Shipped comment | Why it is residue |
|---|---|
| `# Without this a Codex catalog fell through to the single-page renderer` | Describes a bug that never existed on `main` |
| `# this was 99.2% of extract_docs runtime on a 180-plugin repository` | Cites a benchmark from one review round as if it were a live fact |
| `# The direct probes were fixed; the recursive scan was not` | Narrates the order the fixes landed in |
| Test sections headed `Review follow-ups, round three` / `round four` | Organizes tests by when they were written, not what they cover |

Apply the **stranger test** to every comment and docstring in the diff: would
this read as a description of the code to someone opening the file a year from
now who has never seen the PR? If it only makes sense next to the review
thread, it is residue.

### What to flag in code

- **Phantom bugs**: A comment describing a failure mode that never existed in
  the merged code. A reviewer's hypothetical becomes a permanent claim about
  history that no reader can verify.
- **Round-scoped measurements**: Benchmark numbers, percentages, or timings
  captured during review and frozen into a comment. They are stale the moment
  the code changes. Move them to the commit message or PR body.
- **Fix-sequence narration**: Comments that recount which parts were fixed
  when, or that a previous approach was replaced. The file should describe the
  code as it is.
- **Round-numbered test organization**: Test classes, sections, or fixture
  names keyed to review iterations rather than to the behavior under test.
  Rename to the scenario being covered.
- **Change announcements**: `# now also handles X`, `# added to support Y`,
  `# changed from the old approach`. A comment should explain why the code is
  the way it is, not that it moved. Git already records the change.
- **Prose restatements of the code**: A comment that reads the next line back
  in English (`# increment the counter` above `count += 1`) adds nothing and
  goes stale independently of the code.
- **Defensive over-commenting**: Every obvious line annotated. Density is the
  signal — one explanatory comment in a tricky block is good; eight in a row
  over trivial statements is padding.
- **Signature-echo docstrings**: A docstring that lists the parameters and
  their types with no information the signature does not already carry. Either
  say something about behavior, invariants, or failure modes, or drop it.
- **Conversational filler**: `note that`, `as mentioned above`, `keep in mind
  that`, `it's worth pointing out`. Delete the frame and keep the claim.
- **Changelog narration in code**: Dated entries, "v2 behavior", or migration
  history embedded in a module that is not a changelog.

## Part B — Humanizing technical writing

Applies to docs, docstrings, commit messages, PR descriptions, README and site
content, and the skill and rule text this repo ships. Prior art for these
patterns is listed under Reference below.

### Tells to flag in prose

- **AI vocabulary tells**: delve, crucial, pivotal, seamless, robust (as
  filler), comprehensive, leverage (as a verb for "use"), tapestry, landscape,
  underscore, testament, showcase. Flag them when they cluster, not on a single
  hit.
- **Copula avoidance**: "serves as", "stands as", "boasts", "represents a"
  where "is" or "has" is the sentence. `The cache serves as a lookup layer` →
  `The cache is a lookup layer`.
- **Rule-of-three padding**: Ideas forced into triples for rhythm —
  "fast, safe, and maintainable" — where only one or two items carry meaning.
- **Negative parallelism**: "It's not just X, it's Y", "not merely a linter,
  but a…". State the claim directly.
- **Signposting**: "Let's dive in", "Here's what you need to know", "In this
  section we will". Cut the announcement and start with the content.
- **Sycophancy**: "Great question", "You're absolutely right", "Excellent
  catch" surviving into a commit message or PR description.
- **Hedging and filler**: `could potentially`, `it is important to
  note that`, `in order to`, `at this point in time`. Tighten.

### Formatting and shape tells

- **Em dash and boldface abuse**: Em dashes doing the work of every other
  punctuation mark in a paragraph, or bold applied to phrases mechanically
  rather than to genuine key terms. Calibrate against house style first — see
  below.
- **Title Case headings**: `## Configuring The Rule Set` where the surrounding
  docs use sentence case.
- **Manufactured punchlines and staccato drama**: A run of short declarative
  fragments engineered to land, where a normal sentence would do.
- **Generic conclusions**: Upbeat send-off paragraphs that add no fact —
  "This makes skillsaw more powerful than ever". Delete; end on the last
  concrete point.
- **Chatbot artifacts**: "I hope this helps", "Let me know if you'd like me to
  expand on this", trailing offers to continue.

### Rewrite rules

**Never fabricate.** A rewrite suggestion may cut, compress, or restructure, but
it must not introduce a fact, number, name, or rationale absent from the source
or from the code. If a sentence is vague because the underlying fact is unknown,
say what is unknown or recommend cutting the sentence — do not invent a specific
to replace the vague one. Quote the rewrite you are proposing so the author can
accept it verbatim.

## What NOT to flag

This reviewer becomes a nuisance the moment it polices taste. Leave these alone:

- **Long "why" comments that earn their length.** A ten-line comment explaining
  a non-obvious invariant, a workaround for an upstream bug with an issue link,
  or the reason an obvious-looking simplification is wrong is exactly the
  comment the codebase wants. Length is not the signal — diff-anchoring is.
- **Project house style.** skillsaw's own instruction files, skills, and docs
  use em dashes, bold lead-ins on bullets (`- **Term**: …`), and imperative
  headings throughout. Consistency with the surrounding file wins over the
  generic pattern list. Only flag when the new text departs from what the rest
  of the file already does.
- **Domain vocabulary.** "lint tree", "block", "repo type", "frontmatter",
  "splice", "copula", "supply chain" are the project's terms of art, not
  inflated diction. Likewise, formal or unusual words are not AI tells on their
  own; only the specific overused set above is.
- **An em dash doing ordinary work.** One em dash setting off an aside is
  plain English. The tell is density plus other tells in the same paragraph.
- **Version-scoped documents.** Changelogs, release notes, migration guides,
  and the PR description itself are supposed to narrate change. Diff-anchored
  writing is only a defect where the reader has no diff in hand.
- **Comments a reviewer explicitly requested.** If the PR thread shows the
  maintainer asking for an explanatory comment, it stays. Suggest rewording it
  to drop the review framing, not deleting it.
- **Test names that read verbosely** but describe the scenario accurately.
- **Existing text the diff merely moves.** Review what the change writes, not
  every line it touches.

Prefer clustering to isolated hits. One overused word is nothing; three tells in
one paragraph is a finding. Cap the output at the strongest handful of items and
group the rest as a single NOTE rather than filing one per instance.

## Severity calibration

- `BLOCKING`: Slop in shipped text. Review-history residue in code comments —
  any Part A pattern — and clusters of Part B tells dense enough that a section
  reads as generated rather than written. Also any comment or docstring that
  asserts something **factually false** about the shipped code: a wrong
  invariant, a bug that never existed, a stale measurement presented as
  current. Quote the text and quote the replacement, so the author can accept
  it verbatim and clear the finding in one edit.
- `SUGGESTION`: One tell in otherwise clean writing, or a passage that is
  merely weaker than it could be.
- `NOTE`: One-line polish — a filler phrase, a Title Case heading, a single
  signature-echo docstring in a file that is otherwise fine.

Blocking raises the cost of a false positive, so the clustering rule above is a
requirement rather than a preference: one overused word is never a finding. When
a finding turns on taste instead of on residue or a false claim, drop it to
`NOTE` or drop it entirely.

Clean writing is a valid outcome. Say what was checked and move on rather than
manufacturing findings.

## Reference

The Part B pattern set draws on the [humanizer
skill](https://github.com/blader/humanizer) by blader, which catalogues signs of
AI-generated prose across content, language, style, and communication
categories, and on [Wikipedia:Signs of AI
writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing) from
WikiProject AI Cleanup, which humanizer is derived from. Both target
encyclopedic and marketing prose; this scope keeps the patterns that survive the
move to a codebase and drops the ones that do not.
