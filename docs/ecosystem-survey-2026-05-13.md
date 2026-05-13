# Skillsaw Open-Source Skills Survey Report

**Date:** 2026-05-13

## Scope

Surveyed **45 repositories** containing **~2,100 skills** across the agent skills
ecosystem. Includes the official agentskills spec repo, Anthropic's official
skills repo, 4 curated "awesome" link collections, and 39 community/vendor repos
sourced from those collections. Repos range from single-skill projects to
137-skill collections covering domains from AI research to music production to
marketing to security.

## Summary Table

### Original Survey (13 repos)

| Repository | Repo Type | Skills | Errors | Warnings |
|---|---|---|---|---|
| agentskills/agentskills | dot-claude | 0 | 0 | 0 |
| Orchestra-Research/AI-Research-SKILLs | agentskills | 98 | 56 | 300+ |
| wshobson/agents | marketplace | 153 | 100+ | 200+ |
| wshobson/commands | unknown | 0 | 0 | 0 |
| alirezarezvani/claude-skills | marketplace | 246 | 16 | 150+ |
| affaan-m/everything-claude-code | agentskills, dot-claude | 220 | 42 | 200+ |
| hesreallyhim/awesome-claude-code | dot-claude | 0 | 1 | 0 |
| mcollina/skills | agentskills | 11 | 1 | 5 |
| garrytan/gstack | agentskills | 1 | 1 | 15 |
| deanpeters/Product-Manager-Skills | agentskills, marketplace | 47 | 4 | 104 |
| obra/superpowers | agentskills, marketplace | 14 | 0 | 27 |
| veniceai/skills | agentskills, single-plugin | 20 | 1 | 8 |
| phuryn/pm-skills | agentskills, marketplace | 65 | 0 | 41 |

### Expanded Survey (32 additional repos from curated collections)

| Repository | Repo Type | Skills | Errors | Warnings |
|---|---|---|---|---|
| anthropics/skills | agentskills, marketplace | 18 | 3 | 52 |
| angular/skills | agentskills | 2 | 0 | 16 |
| better-auth/skills | agentskills, marketplace | 5 | 5 | 3 |
| coderabbitai/skills | agentskills, single-plugin | 2 | 0 | 3 |
| getsentry/skills | agentskills, marketplace | 25 | 7 | 36 |
| supabase/agent-skills | agentskills, marketplace | 2 | 0 | 8 |
| coreyhaines31/marketingskills | agentskills, marketplace | 41 | 0 | 83 |
| chadboyda/agent-gtm-skills | agentskills, marketplace | 18 | 10 | 20 |
| firecrawl/cli | agentskills, marketplace | 9 | 1 | 1 |
| NeoLabHQ/context-engineering-kit | agentskills, dot-claude, marketplace | 63 | 26 | 485 |
| antonbabenko/terraform-skill | agentskills, marketplace | 1 | 3 | 9 |
| BrianRWagner/ai-marketing-skills | agentskills | 23 | 1 | 32 |
| SHADOWPR0/beautiful_prose | agentskills | 1 | 0 | 0 |
| Leonxlnx/taste-skill | agentskills | 12 | 12 | 54 |
| PSPDFKit-labs/nutrient-agent-skill | agentskills | 1 | 0 | 1 |
| RoundTable02/tutor-skills | agentskills | 2 | 0 | 10 |
| hanfang/claude-memory-skill | unknown | 0 | 0 | 0 |
| grittygrease/safe-encryption-skill | agentskills | 1 | 1 | 4 |
| AgriciDaniel/claude-seo | agentskills, marketplace | 28 | 1 | 56 |
| K-Dense-AI/claude-scientific-skills | agentskills | 137 | 27 | 558 |
| muratcankoylan/Agent-Skills-for-CE | agentskills, marketplace | 15 | 0 | 29 |
| Paramchoudhary/ResumeSkills | agentskills, dot-claude, single-plugin | 27 | 29 | 24 |
| EveryInc/charlie-cfo-skill | agentskills | 1 | 0 | 0 |
| NoizAI/skills | agentskills | 8 | 0 | 2 |
| bitwize-music-studio/claude-ai-music-skills | agentskills, marketplace | 54 | 2 | 50 |
| HeshamFS/materials-simulation-skills | agentskills | 17 | 0 | 12 |
| ZhangHanDong/makepad-skills | agentskills, marketplace | 14 | 17 | 58 |
| Eronred/aso-skills | agentskills, marketplace | 40 | 1 | 9 |
| CloudAI-X/threejs-skills | agentskills | 10 | 0 | 9 |
| BehiSecc/VibeSec-Skill | agentskills | 1 | 2 | 6 |
| ReScienceLab/opc-skills | agentskills, marketplace | 12 | 1 | 20 |
| Joannis/claude-skills | agentskills, marketplace | 14 | 1 | 34 |
| numman-ali/openskills | agentskills | 1 | 0 | 3 |
| MohamedAbdallah-14/unslop | agentskills, marketplace | 13 | 1 | 32 |
| blader/humanizer | agentskills | 1 | 1 | 2 |
| conorluddy/ios-simulator-skill | agentskills, marketplace | 1 | 0 | 4 |

### Gold Standard Repos (zero errors)

These repos demonstrate best practices:

- **SHADOWPR0/beautiful_prose** — 0 errors, 0 warnings. Single skill, direct
  prose, no hedging, proper references. The skill bans em-dashes and practices
  what it preaches.
- **EveryInc/charlie-cfo-skill** — 0 errors, 0 warnings. Clean single-skill
  repo with well-factored `references/` directory. Uses concrete numbers and
  formulas instead of vague language.
- **HeshamFS/materials-simulation-skills** — 0 errors, 12 warnings (all
  minor). 17 skills with excellent structure: per-skill `allowed-tools`
  restrictions, `security_tier` metadata, Bash deliberately excluded from skills
  processing untrusted data.

---

## Part 1: False Positive Analysis

### Confirmed False Positives

#### 1. `content-embedded-secrets` — example/placeholder credentials (~20 instances)

The secret detection regex fires on content that is clearly not real credentials.
Three distinct categories emerged across the expanded survey:

**a) Anti-pattern examples in security skills (getsentry, claude-skills)**

Security-review skills that document vulnerable patterns are inherently full of
example credentials. getsentry/skills had **5 of 7 errors** be false positives:
- `password = "hardcoded"` under heading "### Always Flag (Secrets)"
- `password = 'admin'` labeled `# VULNERABLE: Default/weak credentials`
- `SECRET_KEY = 'development-secret-key'` in the same section
- `AKIAIOSFODNN7EXAMPLE` — AWS's official example key from their documentation

Similarly claude-skills had anti-pattern examples labeled `# BAD` with
corrective `# GOOD` immediately below.

**b) Placeholder API keys (K-Dense-AI, antonbabenko)**

9 false positives in K-Dense-AI/claude-scientific-skills from obvious
placeholders: `api_key = "your_api_key_here"`, `api_key="your-openrouter-api-key"`.
The regex fires because the placeholder string exceeds the 16-character minimum.
antonbabenko/terraform-skill was also flagged for `AKIAIOSFODNN7EXAMPLE`.

**c) Documentation templates (AgriciDaniel, everything-claude-code)**

PEM key headers in JSON templates with `...` as the key content:
`"private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"`

**Root cause:** The rule has no awareness of fenced code blocks, no placeholder
value allowlist, and no well-known example credential denylist.

**Recommendation:** Three-pronged fix:
1. Skip or reduce severity for matches inside fenced code blocks
2. Allowlist placeholder patterns: `your[-_]`, `example`, `REPLACE`, `xxx`,
   `<...>`, bare `...`
3. Denylist well-known example keys: `AKIAIOSFODNN7EXAMPLE`,
   `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`

#### 2. `content-weak-language` — firing on reference files (~300+ instances)

~90% of weak-language warnings in AI-Research-SKILLs and K-Dense-AI are on
`references/*.md` files — scraped third-party documentation where words like
"correctly" and "properly" have legitimate technical meaning (e.g., "Confirm CUDA
is installed correctly" is a troubleshooting step, not hedging).

**Recommendation:** Reduce severity or suppress for `skill-ref` content blocks.

#### 3. `content-negative-only` — "Don't use this when:" scope boundary pattern (~155 instances)

A well-established UX pattern in skill authoring uses sections like
`**Don't use this when:**` followed by conditions listing when a skill should NOT
activate. Found across Product-Manager-Skills, superpowers, pm-skills,
veniceai-skills, and others. This is scope definition, not a behavioral
prohibition.

**Recommendation:** Skip lines matching `don'?t\s+use\b.*\bwhen\s*[:*]`.

#### 4. `content-contradiction` — negation prefix blindness (NeoLabHQ)

The contradiction detector flagged "minimal" vs "exhaustive" as contradictory,
but the word "exhaustive" only appeared as "**non**-exhaustive" — the opposite
meaning. Naive word-level matching without handling negation prefixes causes
false positives.

**Recommendation:** Handle negation prefixes (`non-`, `not `) before flagging
keyword-pair contradictions.

### Confirmed Skillsaw Bug

#### `mcp-valid-json` — string path for mcpServers rejected (bitwize-music-studio)

The `plugin.json` contains `"mcpServers": "./.mcp.json"` (a string path pointing
to a separate file). The Claude Code plugin spec explicitly documents
`mcpServers` as type `string|array|object`, with `"./my-extra-mcp-config.json"`
as an example. The separate `.mcp.json` file exists and contains a proper
`mcpServers` object.

**Root cause:** `_validate_plugin_json_mcp` in `mcp.py` reads the value, finds
a string instead of a dict, and errors. It does not handle the string-path case.

**Impact:** Any repo using the string-path pattern for MCP config will get a
spurious error.

### Not False Positives (Confirmed True Violations)

| Rule | Description | Verdict |
|---|---|---|
| `agentskill-name` | Name/directory mismatches across all repos | **True violations** — spec requires name == parent directory |
| `agentskill-name` (uppercase) | `VibeSec-Skill`, `Resume Tailor`, `makepad-2.0-*` | **True violations** — spec requires `[a-z][a-z0-9-]*` |
| `context-budget` | Oversized SKILL.md files (up to 36K tokens) | **True violations** — should use references/ |
| `context-budget` (agents) | 111,717-token agent in NeoLabHQ | **True violation** — entire spec document as agent prompt |
| `command-frontmatter` | 41 commands in wshobson/agents missing frontmatter | **True violations** — genuinely missing |
| Translated skill frontmatter | Broken YAML in docs/ translations | **True violations** — dropped YAML quoting |

Even **anthropics/skills** (the official Anthropic repo) has true violations:
`claude-api` (8,187 tokens) and `skill-creator` (8,246 tokens) both exceed the
6,000-token error limit.

---

## Part 2: Potentially Missing Rules

Ordered by impact (highest first), incorporating findings from all 45 repos.

### High Priority

#### 1. `content-placeholder-text` (warning)

Detect TODO markers, `[link here]`, `[Insert X]`, unfilled template sections.

- **Product-Manager-Skills:** 28/47 skills have `[If Dean has PRD templates, link here]`
- **AI-Research-SKILLs:** `*Quick reference patterns will be added as you use the skill.*`

#### 2. `content-broken-internal-reference` (warning)

Detect markdown links `[text](path.md)` pointing to files that don't exist.
Resolve paths relative to the containing file. Distinct from
`instruction-imports-valid` (which checks `@import` directives).

**Reliability: very high (~99% precision).** Markdown link syntax is
unambiguous — there is near-zero false positive risk. Across 45 repos: 741
valid linked references vs 184 broken (20% breakage rate in the wild).

- **NeoLabHQ:** 17 broken `./reference/*.md` links across 6 skills (files
  never created)
- **claude-skills:** 145 broken links in `.gemini/skills/` copies (reference
  dirs not copied alongside skills)
- **AI-Research-SKILLs:** 17 broken links to nonexistent reference docs
- **everything-claude-code:** `agent-sort/SKILL.md` references nonexistent
  `skills/skill-library/SKILL.md`

Should skip directories named `template/` or `templates/` where placeholder
links are intentional.

#### 2b. `content-unlinked-internal-reference` (info)

Detect bare path-like strings in markdown content that are not wrapped in link
syntax. These are common in the wild but are not machine-followable links.

**Detection via `patterns`:** The rule ships with sensible defaults and users
can extend or override them:

```yaml
rules:
  content-unlinked-internal-reference:
    patterns:          # defaults shown — override to customize
      - "./**/*.*"
      - "references/**/*.md"
```

Patterns are glob-style and matched against bare path-like strings found in the
content. The defaults cover `./`-prefixed paths (unambiguous — nobody writes
`./something` in prose accidentally) and the `references/` convention common in
the agentskills ecosystem. Teams with their own directory conventions (e.g.,
`docs/`, `guides/`) can add patterns without modifying the rule source.

**Reliability: high (~95% precision).** Across 45 repos: 1,217 valid bare
references vs 390 broken (24% breakage rate). No instances of false-positive
patterns like `pip install references/foo.md` were found.

Three formatting patterns observed:
1. **Backtick-wrapped:** `` `references/foo.md` `` (Joannis, SHADOWPR0)
2. **Bold-listed:** `- **references/foo.md** — description` (Joannis)
3. **Prose directives:** `Reference: references/foo.md` (AI-Research-SKILLs)

Could also offer an **autofix** that wraps bare paths in markdown link syntax
(`references/foo.md` → `[references/foo.md](references/foo.md)`) for better
tooling compatibility.

#### 3. `content-placeholder-secret-allowlist` (improvement to existing rule)

Add placeholder-value allowlist to `content-embedded-secrets`. Prevents 20+
false positives observed across the survey. See Part 1 §1 for details.

#### 4. `content-frontmatter-body-duplication` (info)

Detect same text verbatim in frontmatter `description`/`intent` AND body
`## Purpose` section.

- **Product-Manager-Skills:** 46/47 skills triple-duplicate their description

### Medium Priority

#### 5. `agentskill-dir-naming` (warning)

Dedicated rule flagging non-kebab-case directory names. Currently, the symptom
is caught by the name-mismatch error, but the error message is misleading.

- **better-auth:** `emailAndPassword/`, `twoFactor/` (camelCase)
- **ZhangHanDong:** 14 directories with dots (`makepad-2.0-*`)

#### 6. `content-deprecation-notice` (warning)

Detect skills with "retained for compatibility", "superseded by", or
"deprecated" language.

- **everything-claude-code:** `autonomous-loops/SKILL.md` says it's superseded
  by `continuous-agent-loop` but both still exist

#### 7. `content-keyword-stuffing` (info)

Detect `## Keywords` sections with comma-separated lists.

- **claude-skills:** 56 skills in the c-level-advisor suite

#### 8. `content-self-announcement` (info)

Detect instructions like `Announce at start: "I'm using the X skill..."`.

- **superpowers:** 4 skills; **claude-skills:** 2 skills

#### 9. `content-suggest-references-split` (info)

When a skill exceeds the error threshold AND has no `references/` directory,
suggest splitting content. The existing token-limit error doesn't guide the fix.

- **chadboyda:** All 18 skills are monolithic with zero references/
- **grittygrease:** 14,301-token single file with zero references/

#### 10. `content-boilerplate-footer` (info)

Detect "Skill type:", "Suggested filename:", "Dependencies:" metadata blocks
in the body that should be in frontmatter.

- **Product-Manager-Skills:** 28/47 skills

### Lower Priority

#### 11. `content-duplicate-skill` (info)

Detect identical or near-identical skill content in multiple locations.

- **MohamedAbdallah-14/unslop:** Same skills in `skills/`, `plugins/unslop/skills/`,
  `.cursor/skills/`, `.windsurf/skills/`, and root-level copies

#### 12. Default exclude patterns in config (improvement)

Populate `exclude_patterns` in `LinterConfig.default()` with sensible defaults
rather than hardcoding directory exclusions into discovery logic. Users can
customize in `.skillsaw.yaml`.

Suggested defaults:
```yaml
exclude:
  - "**/template/**"
  - "**/templates/**"
  - "**/_template/**"
```

- **anthropics/skills:** `template/SKILL.md` flagged for name mismatch
- **veniceai/skills:** Same pattern
- **ReScienceLab/opc-skills:** Same pattern
- **muratcankoylan:** `template/SKILL.md` with placeholder `./references/topic-details.md`

#### 13. `content-auto-generated` (info)

Detect scraper-generated skills with boilerplate notices.

- **AI-Research-SKILLs:** 10+ skills with "automatically generated from documentation"

#### 14. `agentskill-unknown-frontmatter-keys` (info)

Warn about non-spec frontmatter keys in SKILL.md (e.g., `version: 2.5.1`).
The `.claude/rules/*.md` validator already does this; SKILL.md does not.

- **blader/humanizer:** `version: 2.5.1` in frontmatter

#### 15. `content-scope-overlap` (info)

Multiple skills in a single repo with significantly overlapping descriptions.

- **wshobson/agents:** 3 debugging plugins, 4 security plugins with unclear boundaries

#### 16. `content-platform-assumption` (info)

Platform-specific commands (`open`, `pbcopy`) without cross-platform fallback.

- **AI-Research-SKILLs, gstack:** macOS-specific `open` command

#### 17. `near-miss-skill-detection` (info)

When repo type is "unknown", scan for files that look like skills but have
wrong names (e.g., `skill/mem.md` instead of `SKILL.md`).

- **hanfang/claude-memory-skill:** `skill/mem.md` not recognized

---

## Part 3: Repo Type Detection Gaps

**`wshobson/commands`** — Detected as "unknown". Uses `tools/` and `workflows/`
directories (legacy slash-commands format). Commands pass clean because plugin
rules don't fire on unknown repo types.

**`hanfang/claude-memory-skill`** — Detected as "unknown". Skill file is at
`skill/mem.md` instead of `SKILL.md`. Skillsaw cannot recognize it.

**Multi-platform layouts** — Several repos (Paramchoudhary/ResumeSkills,
MohamedAbdallah-14/unslop) distribute skills across `.agents/skills/`,
`.cursor/skills/`, `.codex/skills/`, `.windsurf/skills/` using symlinks.
Skillsaw discovers skills via `.claude/skills/` but misses the canonical
`.agents/skills/` location. Symlinked skills report duplicate violations.

---

## Part 4: Curated Collection Findings

The 4 "awesome" repos collectively link to **80+ unique repos** with actual
skills content. From this survey, 32 were cloned and tested. Highest-signal
repos for future testing:

- **Official vendor (not yet tested):** openai/skills, firebase/skills,
  mongodb/skills, redis/agent-skills, flutter/skills
- **Large community (not yet tested):** openaccountants/openaccountants (371
  skills), garrytan/gstack additional skills

---

## Part 5: Ecosystem Patterns

### Common Anti-Patterns Across the Ecosystem

1. **Monolithic SKILL.md files** — The most common error. Skills stuff 6K-36K
   tokens into a single file instead of using `references/`. Affects ~40% of
   repos surveyed.

2. **Name/directory mismatches** — Second most common. Skill authors use
   descriptive names in frontmatter (`implementing-llms-litgpt`) that don't
   match shortened directory names (`litgpt`). Affects ~30% of repos.

3. **Auto-generated content at scale** — K-Dense-AI (137 skills), AI-Research
   (98 skills) show that batch-generated skills amplify every pattern issue into
   hundreds of warnings. A per-rule deduplication cap or summary mode would make
   output actionable.

4. **Multi-platform skill distribution** — Emerging pattern of distributing
   identical skills across `.claude/`, `.cursor/`, `.codex/`, `.windsurf/`,
   `.gemini/` directories via symlinks.

### What Clean Repos Do Right

- **Factor content** — Keep SKILL.md under 3K tokens, move details to
  `references/`
- **Direct language** — Concrete numbers, formulas, and examples instead of
  "properly" and "correctly"
- **Scoped tool access** — Explicit `allowed-tools` per skill, deliberately
  excluding `Bash` when processing untrusted input
- **Match names to directories** — No suffixes, prefixes, or case mismatches

---

## Design: Rule Suppression

Skillsaw needs a mechanism to suppress specific rule violations without removing
the offending content. Two tiers cover the common cases.

### Tier 1: Config-level suppression (per-rule path globs)

For broad suppression — "I don't care about this rule in these files." Configured
in `.skillsaw.yaml` with `excludes` on a per-rule basis:

```yaml
rules:
  content-weak-language:
    excludes:
      - "skills/legacy/**"
      - "skills/vendor/**"
  content-placeholder-text:
    excludes:
      - "skills/templates/**"
```

This is the right tool when an entire directory or file is known to trigger a rule
intentionally (e.g., legacy skills, vendored content, template scaffolding). No
line-number fragility — globs match paths, not positions.

Implementation: extend the per-rule config schema to accept an `excludes`
list of glob patterns. Check during rule dispatch, before the rule's `check()`
method runs. Patterns are relative to the repository root and use the same
`fnmatch` semantics as the top-level `exclude_patterns`.

### Tier 2: Inline HTML comment directives

For surgical suppression — "this specific paragraph is intentional." Uses HTML
comments that are invisible to both rendered markdown and agent consumers:

```markdown
<!-- skillsaw-disable content-weak-language -->
Consider using this approach when appropriate.
<!-- skillsaw-enable content-weak-language -->
```

Also supports disabling multiple rules and block-scoped disable-all:

```markdown
<!-- skillsaw-disable content-weak-language, content-placeholder-text -->
...
<!-- skillsaw-enable -->

<!-- skillsaw-disable-next-line content-embedded-secrets -->
Example: `export API_KEY=sk-example-key-here`
```

**Why HTML comments work here:** Virtually all agent platforms (Claude Code,
Cursor, Copilot, Windsurf, Gemini) strip HTML comments when processing markdown.
The agentskills spec doesn't prohibit them, and HTML comments are the standard
invisible annotation mechanism in markdown — the same pattern `prettier-ignore`
and `eslint-disable` use in their domains. The suppression marker is visible to
skillsaw but invisible to the agent consuming the skill.

Implementation: parse HTML comments during content block extraction. Maintain a
stack of disabled rule IDs per content block. When a violation is about to be
reported, check whether its rule ID is suppressed at that line. The parser should
handle `disable`/`enable` pairs (range), `disable-next-line` (single line), and
bare `disable` without a matching `enable` (rest of file).

### Directives Reference

| Directive | Scope |
|---|---|
| `<!-- skillsaw-disable rule-id -->` | Disables until matching `enable` or end of file |
| `<!-- skillsaw-enable rule-id -->` | Re-enables a specific rule |
| `<!-- skillsaw-enable -->` | Re-enables all currently disabled rules |
| `<!-- skillsaw-disable-next-line rule-id -->` | Disables for the immediately following line only |
| `<!-- skillsaw-disable rule-a, rule-b -->` | Disables multiple rules at once |

---

## Recommendations Summary

### Bugs to File

| Bug | Description | Impact |
|---|---|---|
| `mcp-valid-json` string path | `"mcpServers": "./.mcp.json"` rejected; spec allows string\|array\|object | Any repo using string-path MCP config |
| `content-embedded-secrets` code-fence blindness | Regex fires inside fenced code blocks on example/placeholder credentials | Security-review skills, teaching materials |
| `content-embedded-secrets` no placeholder allowlist | `your_api_key_here` and `AKIAIOSFODNN7EXAMPLE` flagged as real secrets | Scientific skills, terraform skills |
| `content-contradiction` negation blindness | `non-exhaustive` matched as `exhaustive` | Large instruction files with nuanced language |

### Rule Improvements

| Category | Action | Priority |
|---|---|---|
| Fix `content-weak-language` reference file scope | Reduce severity for `skill-ref` content blocks | High |
| Fix `content-negative-only` scope boundary pattern | Skip "don't use (this) when:" headings | Medium |
| Add default exclude patterns | Populate `template/**` etc. in default config | Medium |

### New Rules

| Rule | What it Catches | Priority |
|---|---|---|
| `content-placeholder-text` | TODO, `[link here]`, unfilled templates | High |
| `content-broken-internal-reference` | Markdown links to nonexistent files (99% precision, 184 broken across 45 repos) | High |
| `content-unlinked-internal-reference` | Bare `./` paths and `references/*.md` mentions not wrapped in links; custom patterns configurable (95% precision, 390 instances across 45 repos) | Medium |
| `content-frontmatter-body-duplication` | Description/purpose triple-duplication | Medium |
| `agentskill-dir-naming` | Non-kebab-case directory names | Medium |
| `content-deprecation-notice` | Superseded/deprecated skills still present | Medium |
| `content-suggest-references-split` | Oversized skill with no references/ dir | Medium |
| `content-keyword-stuffing` | SEO-style keyword sections in body | Low |
| `content-self-announcement` | "Announce: I'm using skill X" | Low |
| `content-duplicate-skill` | Identical content in multiple locations | Low |
| `near-miss-skill-detection` | `skill/mem.md` instead of `SKILL.md` | Low |
