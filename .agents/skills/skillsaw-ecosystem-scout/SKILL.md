---
name: skillsaw-ecosystem-scout
description: Survey the AI coding assistant and agentic tool ecosystem, assess skillsaw's competitive position, identify emerging patterns and missing capabilities, and produce a prioritized strategic report as a GitHub issue.
compatibility: Requires git, gh CLI, and internet access (WebFetch, WebSearch)
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Ecosystem Scout

You are conducting a strategic assessment of the AI coding assistant and agentic
tool ecosystem. Your goal is to identify what skillsaw should support next to
maximize open-source adoption and mindshare.

This skill produces **analysis, not code**. The output is a GitHub issue with a
structured report and prioritized recommendations.

## Step 1: Catalog skillsaw's current capabilities

Before looking outward, establish what skillsaw does today by reading the codebase:

- `src/skillsaw/rules/builtin/__init__.py` — full list of builtin rules
- `src/skillsaw/context.py` — supported repository types
- `README.md` — feature set (linting, scaffolding, doc generation, CI action)
- `.skillsaw.yaml.example` — full config surface
- `src/skillsaw/marketplace/cli.py` and `src/skillsaw/marketplace/add.py` — scaffolding capabilities

Summarize: what formats does skillsaw validate? What can it scaffold? What specs
does it track? What repository types does it detect?

## Step 2: Discover and survey the AI coding assistant ecosystem

Use WebSearch to find the current landscape. Do not rely on a hardcoded list of
tools — the ecosystem changes fast. Run searches like:

- "AI coding assistant tools {current year}"
- "AI coding assistant plugin format"
- "AI coding assistant rules configuration"
- "AI coding assistant marketplace registry"
- "new AI coding assistants {current year}"
- "agentic coding tools open source"

Follow up on each significant tool you find. Fetch their documentation with
WebFetch and identify configuration/skill/plugin formats. For each tool
discovered, record:

1. What configuration file formats does it use?
2. Does it have a concept of skills/plugins/extensions?
3. Does it have a marketplace or registry?
4. Does it support MCP? What MCP-related configuration?
5. What validation or linting exists for its formats (if any)?
6. How large/active is the community? (star counts, contributor activity, downloads)

Cast a wide net. The goal is to discover tools and formats skillsaw does not yet
know about, not just to check the ones it already supports.

## Step 3: Survey competing linters, scaffolding tools, and developer tooling

skillsaw is a linter, scaffolder, and doc generator. Search for anything that
overlaps with or competes against these capabilities:

- "AI coding assistant linter"
- "AI agent config validator"
- "cursor rules linter"
- "MCP server linter validator"
- "AI coding assistant scaffolding tool"
- "AI agent plugin generator scaffold"
- "AI rules file generator"
- "dotfiles linter AI assistant"

For each competing tool found, determine:

- What does it lint, validate, or scaffold?
- What formats does it support?
- How mature is it? (GitHub stars, npm/pip downloads, last commit date)
- What does it do that skillsaw does not?
- What does skillsaw do that it does not?
- Is it gaining traction or stalled?

Also look for adjacent developer tooling that could inform skillsaw's roadmap:
IDE extensions, CLI tools, CI actions, or registries that serve the same
ecosystem.

## Step 4: Survey agent protocols and emerging standards

Use WebSearch to discover what protocols and standards are gaining traction:

- "agent communication protocol standard {current year}"
- "agent-to-agent protocol"
- "MCP server registry validation"
- "AI agent interoperability standard"
- "agentic AI configuration format standard {current year}"
- "skill sharing format AI agents"

For each protocol or standard found, determine:

- What is it? Who is behind it?
- How mature is it? (spec draft, stable, widely adopted)
- Does it define file formats or configuration that a linter could validate?
- Is adoption growing or stalled?

Look for convergence trends — are multiple tools adopting the same formats?
Are there interoperability initiatives emerging?

## Step 5: Identify user pain points and unmet needs

Search for what problems developers are actually hitting and asking for help
with. Look at forums, discussions, and issue trackers:

- "AI coding assistant rules not working"
- "cursor rules best practices"
- "claude code plugin problems"
- "MCP server configuration issues"
- "AI agent skill debugging"
- "managing AI coding assistant config across team"

Also search GitHub Issues, Discussions, and Reddit for complaints, workarounds,
and feature requests related to AI assistant configuration. Look for patterns:

- What do people struggle with when writing rules or plugins?
- What breaks when teams share or standardize AI assistant config?
- What manual steps do people wish were automated?
- What quality or security concerns do people raise about skills/plugins?
- Are there common "how do I validate my X?" questions with no good answer?

The goal is to find **real demand signals** — problems people are already having
that skillsaw could solve. These are higher-value than features nobody asked for.

## Step 6: Assess skillsaw's competitive position

Compare the baseline from Step 1 against findings from Steps 2–5. For each
ecosystem tool or format, classify as:

- **Already supported** — skillsaw validates this today. Note the current rules.
- **Partially supported** — skillsaw covers some aspects but is missing fields,
  features, or format versions.
- **Not supported but feasible** — a clear, stable format exists that skillsaw
  could validate with new rules.
- **Not supported and unclear** — the format is too new, unstable, or
  undocumented for reliable validation.
- **No format to validate** — the tool has no configuration format a linter could
  check.

## Step 7: Identify highest-impact opportunities

Rank opportunities by likely impact on open-source adoption. Consider:

- **User base size** — how many developers use this tool? Rules for tools with
  millions of users have more reach than niche tools.
- **Format stability** — is the format stable enough to write durable rules?
  Unstable formats mean maintenance burden.
- **Competitive gap** — is skillsaw the only linter that could serve this format?
  Being first matters.
- **Implementation effort** — how much work? A new RepositoryType and rule set vs.
  a single new rule.
- **Cross-format synergy** — does supporting this format benefit existing users?
  Many repos have both `.cursor/rules/` and `.claude/rules/`.

Produce a ranked list of recommended actions, each with:

| Field | Description |
|-------|-------------|
| **What** | The format or capability to add |
| **Why** | The strategic rationale |
| **Effort** | Low / Medium / High |
| **Impact** | Low / Medium / High |
| **Depends on** | Any prerequisites |

## Step 8: Check for new primitives and concepts

Beyond format validation, look for new categories of capability:

- **Skill testing/evaluation** — are there emerging standards for testing skills?
- **Skill interoperability** — can skills be shared across tools? Is a universal
  format emerging?
- **Security scanning** — beyond MCP allowlisting, are there security concerns in
  skill/plugin formats that a linter should catch?
- **Dependency management** — emerging patterns for skill dependencies, versioning,
  or compatibility declarations?
- **Agent orchestration config** — new formats for multi-agent workflows?
- **Quality metrics** — download counts, ratings, trust signals for
  skills/plugins?

## Step 9: Produce the strategic report

Create a GitHub issue using `gh issue create` with:

- **Title:** `[Ecosystem Scout] Strategic Assessment - {YYYY-MM-DD}`
- **Labels:** `ecosystem` (create the label if it does not exist)

Use this structure for the issue body:

```markdown
## Ecosystem Scout Report

**Date**: {date}
**skillsaw version**: {version from pyproject.toml}

### Current Capabilities Summary
{Brief summary of what skillsaw supports today}

### Ecosystem Landscape

#### AI Coding Assistants
| Tool | Config Format(s) | Skills/Plugins? | Marketplace? | MCP? | Community Size | skillsaw Support |
|------|------------------|-----------------|--------------|------|----------------|------------------|
| ... | ... | ... | ... | ... | ... | ... |

#### Competing Linters & Tooling
| Tool | What it does | Formats | Traction | Gap vs skillsaw |
|------|-------------|---------|----------|-----------------|
| ... | ... | ... | ... | ... |

#### Agent Protocols
| Protocol | Status | Relevance to skillsaw |
|----------|--------|----------------------|
| ... | ... | ... |

### User Pain Points & Unmet Needs
{Problems developers are hitting, demand signals from forums/issues/discussions}

### Competitive Assessment
{For each tool/format: detailed status and gap analysis}

### Prioritized Recommendations

#### High Priority
{Ranked list with What / Why / Effort / Impact}

#### Medium Priority
{Ranked list}

#### Low Priority / Watch List
{Items to monitor but not act on yet}

### New Primitives & Concepts
{Emerging patterns that could inform skillsaw's roadmap}

### Raw Research Notes
<details>
<summary>Detailed findings per tool</summary>
{Full notes from each tool surveyed}
</details>

---
Generated by the [skillsaw-ecosystem-scout](https://github.com/stbenjam/skillsaw) skill.
```

## Step 10 (Optional): Create tracking issues

Only if the user explicitly requests it (e.g., via `--create-issues` or by asking
in the prompt), create individual GitHub issues for each high-priority
recommendation:

- **Title:** `[Ecosystem] {brief description}`
- **Labels:** `ecosystem`
- **Body:** The recommendation details from the report, with a link back to the
  main assessment issue.

Do not create tracking issues unless explicitly asked.

## Important constraints

- This skill produces analysis, not code changes. **Never create PRs.**
- Use WebFetch for known URLs and WebSearch for discovery. Both are needed.
- Be specific — cite URLs, version numbers, star counts, and dates.
- Do not recommend adding support for formats that are proprietary,
  undocumented, or likely to change drastically within months.
- If a web fetch fails (site down, URL changed), note the failure and move on.
  Do not block the entire report on one failed fetch.
- Recommendations must be actionable. Bad: "consider supporting more tools."
  Good: "Add Cursor rules validation (`.cursor/rules/*.mdc` with YAML
  frontmatter) — Cursor has 2M+ users and no existing linter for this format."
