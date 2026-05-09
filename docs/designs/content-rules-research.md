# Content Intelligence Rules — Research & Justification

skillsaw's content intelligence rules analyze the *quality* of AI context
building blocks (skills, instructions, etc.). Each rule is grounded in published
research on LLM behavior, prompt engineering best practices, or established
software engineering principles.

This document explains **why each rule exists**, and what research supports it.

---

## Table of Contents

- [content-weak-language](#content-weak-language)
- [content-tautological](#content-tautological)
- [content-critical-position](#content-critical-position)
- [content-redundant-with-tooling](#content-redundant-with-tooling)
- [content-instruction-budget](#content-instruction-budget)
- [content-negative-only](#content-negative-only)
- [content-section-length](#content-section-length)
- [content-contradiction](#content-contradiction)
- [content-hook-candidate](#content-hook-candidate)
- [content-actionability-score](#content-actionability-score)
- [content-cognitive-chunks](#content-cognitive-chunks)
- [content-embedded-secrets](#content-embedded-secrets)
- [content-banned-references](#content-banned-references)
- [content-inconsistent-terminology](#content-inconsistent-terminology)
- [Instruction Budget vs. Context Budget](#instruction-budget-vs-context-budget)
- [Key Papers (Cross-Cutting)](#key-papers-cross-cutting)

---

## content-weak-language

**Detects hedging and vague language** ("try to", "maybe consider", "if
possible") in instruction files.

LLMs respond to direct, assertive instructions. Hedging language introduces
ambiguity about whether the instruction is mandatory or optional, and the model
may treat it as the latter. Bsharat et al. tested 26 prompting principles and
found that direct language ("Your task is", "You MUST") yielded **57.7% quality
improvement** over hedged equivalents.

Anthropic's own prompting guide says: *"Claude performs best with clear, direct
instructions."* OpenAI's guide echoes this: *"The more specific and detailed
your instructions, the more likely you'll receive the output you want."*

**References:**

- Bsharat et al., [Principled Instructions Are All You Need for Questioning
  LLaMA-1/2, GPT-3.5/4](https://arxiv.org/abs/2312.16171) (arXiv:2312.16171,
  Dec 2023) — Principles #1 and #6
- [Anthropic Prompting Best
  Practices](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/be-clear-and-direct)
  — "Be clear and direct"
- [OpenAI Prompt Engineering
  Guide](https://platform.openai.com/docs/guides/prompt-engineering) —
  "Write clear instructions"

---

## content-tautological

**Detects instructions the model already follows by default** ("write clean
code", "follow best practices", "be thorough").

These instructions consume context tokens without adding signal. Anthropic's
context engineering guide warns: *"Be thoughtful and keep your context
informative, yet tight."* Every tautological instruction dilutes the model's
attention across tokens that carry zero new information. Levy et al. demonstrated
that reasoning performance degrades at ~3,000 prompt tokens — every wasted token
brings you closer to that cliff.

The Claude Code best practices documentation is explicit: *"Ask yourself: 'If I
remove this line, will Claude make mistakes?' If the answer is no, cut it. Every
line must earn its place."*

**References:**

- Levy, Jacoby & Goldberg, [Same Task, More
  Tokens](https://arxiv.org/abs/2402.14848) (arXiv:2402.14848, ACL 2024) —
  Reasoning degrades at ~3,000 prompt tokens
- [Anthropic: Effective Context Engineering for AI
  Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  (2025) — "Keep your context informative, yet tight"
- [Claude Code Best
  Practices](https://docs.anthropic.com/en/docs/claude-code/best-practices) —
  "Every line must earn its place"

---

## content-critical-position

**Flags critical instructions buried in the middle of files** where LLM
attention is lowest.

The "lost in the middle" effect is one of the most replicated findings in LLM
research. Liu et al. showed that LLM performance follows a **U-shaped curve**:
information at the beginning and end of context is recalled reliably, while
information in the middle is significantly degraded. This has been replicated
across all tested model families.

The implication for instruction files is clear: if you mark something as
IMPORTANT or CRITICAL, it should be at the top of the file — not buried between
routine instructions at line 47.

**References:**

- Liu et al., [Lost in the Middle: How Language Models Use Long
  Contexts](https://arxiv.org/abs/2307.03172) (arXiv:2307.03172, TACL 2024) —
  The foundational U-shaped attention curve paper
- [Serial Position Effects of Large Language
  Models](https://arxiv.org/abs/2406.15981) (arXiv:2406.15981, Jun 2024) —
  Confirms primacy and recency biases analogous to human cognition
- Chroma Research, [Context Rot: How Increasing Input Tokens Impacts LLM
  Performance](https://research.trychroma.com/context-rot) (Jul 2025) — Tested
  18 frontier models, confirms lost-in-the-middle across all of them

---

## content-redundant-with-tooling

**Detects instructions that duplicate what .editorconfig, ESLint, Prettier, or
tsconfig already enforce.**

When CLAUDE.md says "use 2-space indentation" and `.editorconfig` already
specifies `indent_size = 2`, the instruction is redundant. Worse, it creates
configuration drift risk: if someone updates `.editorconfig` to 4 spaces but
forgets the CLAUDE.md, the model receives contradictory signals.

Tooling enforcement is **deterministic** — it runs every time, without fail.
Instruction-file enforcement is **probabilistic** — the model follows it most of
the time, but not always. Restating deterministic rules as probabilistic
instructions wastes context tokens and adds no reliability.

**References:**

- Levy, Jacoby & Goldberg, [Same Task, More
  Tokens](https://arxiv.org/abs/2402.14848) — Every redundant instruction
  consumes context budget
- [Anthropic: Effective Context
  Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  — "One of the most common failure modes we see is bloated tool sets" — applies
  equally to bloated instructions
- [Dotzlaw: Claude Code
  Hooks](https://www.dotzlaw.com/insights/claude-hooks/) — "CLAUDE.md
  instructions are advisory… Hooks are enforcement"

---

## content-instruction-budget

**Warns when the count of imperative instructions in a single file exceeds
~150.**

This rule counts **discrete directives** (lines starting with imperative verbs
like "use", "always", "never", "ensure"), not raw tokens. The threshold is based
on research showing that LLM instruction-following success degrades as a function
of instruction *count*, independent of token length.

The "Curse of Instructions" paper (ICLR 2025) demonstrated that the probability
of following all N instructions equals (individual success rate)^N — exponential
decay. GPT-4o achieved only 15% success at just 10 simultaneous instructions.
The IFScale benchmark (2025) extended this to 500 instructions and found that
**primacy bias becomes dominant at 150–200 instructions**: models begin
selectively attending to earlier instructions and ignoring later ones.

The ~150 threshold is where most models cross from "degraded but functional" to
"selectively ignoring instructions."

See [Instruction Budget vs. Context Budget](#instruction-budget-vs-context-budget)
for how this differs from the `context-budget` rule.

**References:**

- [Curse of Instructions: Large Language Models Cannot Follow Multiple
  Instructions at Once](https://openreview.net/forum?id=R6q67CDBCH) (ICLR 2025)
  — Success rate = p^N; exponential decay with instruction count
- Jaroslawicz et al., [How Many Instructions Can LLMs Follow at
  Once?](https://arxiv.org/abs/2507.11538) (arXiv:2507.11538, Jul 2025) —
  IFScale benchmark up to 500 instructions; primacy bias strongest at 150–200
- Levy, Jacoby & Goldberg, [Same Task, More
  Tokens](https://arxiv.org/abs/2402.14848) — Reasoning degrades at ~3,000
  tokens; 150 instructions ≈ 1,500 tokens, leaving headroom

---

## content-negative-only

**Detects prohibitions without a positive alternative** ("don't use global
variables" without saying what to use instead).

The "Pink Elephant Problem" is well-documented: telling an LLM to avoid
something can actually **increase** the likelihood of that thing appearing. The
EleutherAI/SynthLabs paper demonstrated that baseline instruction-tuned models
*became more likely to mention forbidden topics when explicitly told to avoid
them*.

Both Anthropic and OpenAI recommend affirmative directives. Anthropic's docs
state: *"Positive examples tend to be more effective than negative examples or
instructions that tell the model what not to do."*

**References:**

- [Suppressing Pink Elephants with Direct Principle
  Feedback](https://arxiv.org/abs/2402.07896) (arXiv:2402.07896, Feb 2024) —
  Demonstrates the Pink Elephant Problem in LLMs
- [Negation: A Pink Elephant in the Large Language Models'
  Room?](https://arxiv.org/abs/2503.22395) (arXiv:2503.22395, Mar 2025) —
  Negations remain a "substantial challenge" for LLMs
- Bsharat et al., [Principled Instructions Are All You
  Need](https://arxiv.org/abs/2312.16171) — Principle #4: "Employ affirmative
  directives"
- [Anthropic Prompting Best
  Practices](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/be-clear-and-direct)
  — "Positive examples are more effective"

---

## content-section-length

**Warns about markdown sections exceeding ~500 estimated tokens.**

Long monolithic text blocks degrade both human readability and LLM attention.
The lost-in-the-middle effect operates *within* sections: the longer a
contiguous block of text, the worse recall becomes for information in its
interior. Breaking content into smaller sections with headings creates natural
retrieval anchors.

The ~500 token threshold aligns with RAG chunking research. Pinecone's chunking
guide recommends ~512 tokens as the standard baseline for optimal retrieval and
comprehension. The threshold is configurable via the `max-tokens` parameter.

**References:**

- Liu et al., [Lost in the
  Middle](https://arxiv.org/abs/2307.03172) — Attention degrades within long
  contiguous blocks
- Chroma, [Context
  Rot](https://research.trychroma.com/context-rot) — Attention dilution is
  quadratic in token count
- [Pinecone: Chunking Strategies for LLM
  Applications](https://www.pinecone.io/learn/chunking-strategies/) — 512 tokens
  as standard chunking baseline
- Miller, G. A. (1956), [The Magical Number Seven, Plus or Minus
  Two](https://psycnet.apa.org/record/1957-02914-001) — Working memory limits
  and the value of chunking

---

## content-contradiction

**Detects likely contradictions within instruction files** using keyword-pair
heuristics (e.g., "move fast and iterate quickly" vs. "write comprehensive tests
for every change").

Contradictory instructions force the model to resolve an impossible constraint
at inference time. Research shows this produces "numerous logical errors" — the
model doesn't fail gracefully, it fails silently by picking one interpretation
non-deterministically.

The DIM-Bench benchmark (2025) tested all major models and found *"no LLM
demonstrates complete robustness against instructional distractions."*
Contradictions are the most damaging form of distraction because they create
instructions that cannot be simultaneously satisfied.

**References:**

- [When Prompts Go Wrong: Evaluating Code Model Robustness to Contradictory Task
  Descriptions](https://arxiv.org/abs/2507.20439) (arXiv:2507.20439, Jul 2025)
  — Contradictions yield RIR >80% for GPT-4
- [LLMs can be easily Confused by Instructional
  Distractions](https://arxiv.org/abs/2502.04362) (arXiv:2502.04362, Feb 2025)
  — DIM-Bench: no model is robust to conflicting instructions
- Wallace et al., [The Instruction
  Hierarchy](https://arxiv.org/abs/2404.13208) (arXiv:2404.13208, OpenAI, Apr
  2024) — Models struggle with conflicting instructions across privilege levels

---

## content-hook-candidate

**Identifies instructions that should be automated as hooks** instead of prose
instructions (e.g., "always run tests before committing").

Instructions like "run tests before every commit" are advisory — the model
follows them probabilistically. A pre-commit hook runs deterministically, every
time, without fail. When an instruction describes a mechanical, automatable
action, it should be a hook.

As one practitioner put it: *"The hook does not forget. It does not reason. It
does not skip."* Instruction files should focus on judgment calls and
context-dependent decisions that only the model can make. Automatable actions
belong in hooks.

**References:**

- [Dotzlaw: Claude Code Hooks: The Deterministic Control
  Layer](https://www.dotzlaw.com/insights/claude-hooks/) — "Unlike CLAUDE.md
  instructions which are advisory, hooks are deterministic"
- [Claude Code
  Security](https://docs.anthropic.com/en/docs/claude-code/security) — Hooks
  provide deterministic enforcement
- [aitmpl.com: Block API Keys & Secrets from Your Commits with Claude Code
  Hooks](https://aitmpl.com/blog/security-hooks-secrets/) — "CLAUDE.md rules
  are suggestions. Hooks are enforcement."

---

## content-actionability-score

**Scores instruction files on actionability** — verb density, command
references, file path mentions.

Instruction files full of passive descriptions ("the system architecture is
microservices-based") give the model no direction. Files with imperative verbs
("use microservices architecture for all new services") give clear marching
orders.

Google's Gemini prompting guide states: *"Always remember to include a verb or
command as part of your task — this is the most important part of a prompt."*
The Bsharat et al. study confirmed that imperative framing is one of the
strongest predictors of prompt quality.

**References:**

- Bsharat et al., [Principled Instructions Are All You
  Need](https://arxiv.org/abs/2312.16171) — Imperative framing as a quality
  predictor
- [Google Workspace Gemini Prompt
  Guide](https://services.google.com/fh/files/misc/gemini_for_workspace_prompt_guide_october_2024_digital_final.pdf)
  — "Always include a verb or command"
- [OpenAI Prompt Engineering
  Guide](https://platform.openai.com/docs/guides/prompt-engineering) — "Specify
  the steps required to complete a task"
- [IBM Prompt Engineering
  Techniques](https://www.ibm.com/think/topics/prompt-engineering-techniques) —
  "The request should be an action verb: 'analyze', 'summarize', 'classify'"

---

## content-cognitive-chunks

**Checks that instruction files are organized into cognitive chunks with
headings.**

Working memory is limited to ~4–7 items (Miller, 1956; revised to ~4 by Cowan,
2001). Headings create chunk boundaries that reduce cognitive load for both
humans editing the file and the model processing it. A 60-line file with no
headings is a single undifferentiated block; the same content split into 4
headed sections is 4 discrete, navigable chunks.

For LLMs specifically, headings serve as natural delimiters. OpenAI's guide
recommends: *"Use delimiters to clearly indicate distinct parts of the input."*
Markdown headings are the idiomatic delimiter for instruction files.

**References:**

- Miller, G. A. (1956), [The Magical Number Seven, Plus or Minus
  Two](https://psycnet.apa.org/record/1957-02914-001) — Working memory limits
- [NN/g: How Chunking Helps Content
  Processing](https://www.nngroup.com/articles/chunking/) — "Presenting content
  in chunks makes scanning easier and improves comprehension"
- [OpenAI Prompt Engineering
  Guide](https://platform.openai.com/docs/guides/prompt-engineering) — "Use
  delimiters to clearly indicate distinct parts"
- [Claude Code Best
  Practices](https://docs.anthropic.com/en/docs/claude-code/best-practices) —
  Recommends progressive disclosure with clear headings

---

## content-embedded-secrets

**Detects potential API keys, tokens, and passwords in instruction files.**

CLAUDE.md files are loaded into context every session. A hardcoded API key in
an instruction file is exposed to every conversation, every collaborator, and
potentially every model provider's logging infrastructure. This is
[CWE-798](https://cwe.mitre.org/data/definitions/798.html) (Use of Hard-coded
Credentials), mapping to OWASP Top Ten 2021 A07.

**References:**

- [CWE-798: Use of Hard-coded
  Credentials](https://cwe.mitre.org/data/definitions/798.html) — Authoritative
  weakness enumeration
- [OWASP Secrets Management Cheat
  Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [Claude Code
  Security](https://docs.anthropic.com/en/docs/claude-code/security) —
  Instruction files are loaded into context every session

---

## content-banned-references

**Detects deprecated model names, retired APIs, and custom banned patterns.**

LLMs trained on older data generate deprecated API calls 70–90% of the time when
given outdated context (Wang et al., ICSE 2025). An instruction file that says
"use claude-2 for summarization" or "call /v1/complete" becomes that outdated
context — the model will generate code targeting APIs that no longer exist.

The rule ships with built-in patterns for deprecated Anthropic and OpenAI models
and supports user-defined patterns via the `banned` config key.

**References:**

- Wang et al., [LLMs Meet Library Evolution: Evaluating Deprecated API Usage in
  LLM-based Code](https://yebof.github.io/assets/pdf/wang2025icse.pdf) (ICSE
  2025) — 70–90% deprecated API usage rates with outdated context
- [OpenAI
  Deprecations](https://platform.openai.com/docs/deprecations) —
  Ongoing model and API churn
- [Fern: Documentation Maintenance
  Guide](https://buildwithfern.com/post/documentation-maintenance-best-practices)
  — "AI agents treat documentation as ground truth and cannot detect errors
  through experience"

---

## content-inconsistent-terminology

**Detects inconsistent terminology across instruction files** (e.g., one file
says "directory" while another says "folder").

If one file says "run `npm test`" and another says "execute `yarn test`", the
model must resolve the ambiguity at inference time. The "Curse of Instructions"
paper shows that instruction conflicts compound multiplicatively — inconsistent
terminology creates implicit contradictions that degrade compliance.

Consistent terminology is a well-established principle in technical writing. For
LLMs, it's even more important: the model lacks the human ability to infer that
two different terms refer to the same concept from broader context.

**References:**

- [Curse of Instructions](https://openreview.net/forum?id=R6q67CDBCH) (ICLR
  2025) — Contradictions compound multiplicatively
- [TextUnited: Why Consistent Terminology Matters in Technical
  Documentation](https://textunited.com/en/blog/why-consistent-terminology-is-critical-for-technical-documentation)
  — "Inconsistent terminology can confuse readers, forcing them to guess whether
  different terms refer to the same concept"

---

## Instruction Budget vs. Context Budget

skillsaw has two separate budget rules that measure different things:

### `content-instruction-budget` — How many directives?

Counts **discrete imperative instructions** per file using regex matching on
imperative verb patterns (lines starting with "use", "always", "never",
"ensure", etc.). Code blocks are stripped first.

| Threshold | Severity |
|-----------|----------|
| 80–119 instructions | INFO |
| 120–150 instructions | WARNING |
| 150+ instructions | ERROR |

**Why it matters:** The "Curse of Instructions" (ICLR 2025) showed that the
probability of following all N instructions equals p^N — exponential decay. At
p = 0.99 and N = 150, the probability of following all instructions is only
~22%. The IFScale benchmark confirmed that primacy bias (selectively ignoring
later instructions) becomes dominant at 150–200 instructions.

This is about **cognitive load on the model** — too many simultaneous directives
exceed the model's instruction-following capacity regardless of how many tokens
they occupy.

### `context-budget` — How many tokens?

Measures **estimated token count** (chars ÷ 4) of each individual file, checked
per-file against category-specific thresholds.

| Category | Warn | Error |
|----------|------|-------|
| CLAUDE.md, AGENTS.md, GEMINI.md | 6,000 | 12,000 |
| Instruction files (Cursor, Copilot, Kiro) | 4,000 | 8,000 |
| Skills | 3,000 | 6,000 |
| Commands, agents, rules | 2,000 | 4,000 |

**Why it matters:** Raw token count determines how much of the context window
the file consumes and how severely attention degrades. Levy et al. showed
reasoning performance degrades at ~3,000 tokens. Chroma's "Context Rot" study
found that attention dilution is **quadratic** in token count — doubling the
tokens more than doubles the accuracy loss.

This is about **context window consumption** — a single file that's too large
will crowd out other context and degrade attention across the board.

### The distinction

A file with 50 instructions in 5,000 tokens (verbose prose around each one) has
a low instruction budget but high context budget. A file with 200 terse
one-line instructions in 2,000 tokens has a high instruction budget but low
context budget. Both degrade model performance, but through different mechanisms.

| | Instruction Budget | Context Budget |
|---|---|---|
| **Measures** | Discrete imperative count | Estimated token count |
| **Scope** | Per-file | Per-file |
| **Degradation mechanism** | Instruction-following capacity | Attention dilution |
| **Research basis** | Curse of Instructions (ICLR 2025) | Same Task, More Tokens (ACL 2024) |

---

## Key Papers (Cross-Cutting)

These papers justify multiple rules simultaneously:

| Paper | Venue | Rules |
|-------|-------|-------|
| Liu et al., [Lost in the Middle](https://arxiv.org/abs/2307.03172) | TACL 2024 | critical-position, section-length, cognitive-chunks |
| [Curse of Instructions](https://openreview.net/forum?id=R6q67CDBCH) | ICLR 2025 | instruction-budget, contradiction, inconsistent-terminology |
| Jaroslawicz et al., [How Many Instructions Can LLMs Follow at Once?](https://arxiv.org/abs/2507.11538) | arXiv 2025 | instruction-budget |
| Levy, Jacoby & Goldberg, [Same Task, More Tokens](https://arxiv.org/abs/2402.14848) | ACL 2024 | tautological, redundant-with-tooling, instruction-budget, section-length |
| Bsharat et al., [Principled Instructions Are All You Need](https://arxiv.org/abs/2312.16171) | arXiv 2023 | weak-language, negative-only, actionability-score |
| [Suppressing Pink Elephants](https://arxiv.org/abs/2402.07896) | arXiv 2024 | negative-only |
| Chroma, [Context Rot](https://research.trychroma.com/context-rot) | 2025 | critical-position, instruction-budget, section-length |
| [When Prompts Go Wrong](https://arxiv.org/abs/2507.20439) | arXiv 2025 | contradiction |
| [Anthropic: Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 2025 | tautological, redundant-with-tooling, instruction-budget |
| Wang et al., [LLMs Meet Library Evolution](https://yebof.github.io/assets/pdf/wang2025icse.pdf) | ICSE 2025 | banned-references |
