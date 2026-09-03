#!/usr/bin/env python3
"""Generate README.md rules documentation when generated sections are present."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from skillsaw.rules.builtin import BUILTIN_RULES
from skillsaw.config import LinterConfig

BEGIN_MARKER = "<!-- BEGIN GENERATED RULES -->"
END_MARKER = "<!-- END GENERATED RULES -->"
TOC_BEGIN = "<!-- BEGIN GENERATED TOC -->"
TOC_END = "<!-- END GENERATED TOC -->"

RULE_GROUPS = [
    (
        "Agent Plugins",
        ["agent-plugin-json-valid", "agent-plugin-mcp-valid", "agent-plugin-required"],
        "Validates portable plugin packages against the "
        "[Agent Plugins v1 specification]"
        "(https://agent-plugins.org/specification). The manifest rule checks "
        "the required root `plugin.json`; the MCP rule checks optional root "
        "`mcp.json`. Auto-enabled when a root or immediate `plugins/*` "
        "manifest declares a canonical Agent Plugins schema; use "
        "`--type agent-plugin` to force validation.",
    ),
    (
        "agentskills.io",
        [
            "agentskill-valid",
            "agentskill-name",
            "agentskill-rename-refs",
            "agentskill-description",
            "agentskill-structure",
            "agentskill-evals",
            "agentskill-evals-required",
            "agentskill-unreferenced-files",
        ],
        "These rules validate skills against the [agentskills.io specification]"
        "(https://agentskills.io/specification). They auto-enable wherever skills "
        "are detected — agentskills repos, single plugins, marketplaces, "
        "`.claude/` directories, Codex plugins and marketplaces, Grok Build "
        "plugins and marketplaces, and Agent Plugin packages.",
    ),
    (
        "APM (Agent Package Manager)",
        ["apm-yaml-valid", "apm-structure-valid"],
        "Validates repositories using the [APM](https://github.com/microsoft/apm) "
        "directory layout (`.apm/`). Auto-enables when `.apm/` is detected.",
    ),
    (
        "Claude Code",
        [
            "claude-plugin-json-required",
            "claude-plugin-json-valid",
            "claude-plugin-naming",
            "claude-plugin-readme",
            "claude-command-naming",
            "claude-command-frontmatter",
            "claude-command-sections",
            "claude-command-name-format",
            "claude-agent-frontmatter",
            "claude-marketplace-json-valid",
            "claude-marketplace-registration",
            "claude-settings-dangerous",
            "claude-rules-valid",
        ],
        "Validates the Claude Code formats: plugin manifests "
        "(`.claude-plugin/plugin.json`), `marketplace.json` catalogs, "
        "command and agent frontmatter, `.claude/settings.json` security, "
        "and `.claude/rules/` files. These rules carry the `claude-` prefix "
        "(mirroring `codex-`); their pre-0.18 bare names still work as "
        "legacy aliases everywhere a rule is named.",
    ),
    (
        "CodeRabbit",
        ["coderabbit-yaml-valid", "coderabbit-schema-valid"],
        "Validates `.coderabbit.yaml` config files for YAML syntax. "
        "Instruction text fields (`reviews.instructions`, per-path "
        "instructions, per-tool instructions, `chat.instructions`) are "
        "automatically checked by the content-* rules above. Auto-enabled "
        "when `.coderabbit.yaml` is detected.",
    ),
    (
        "Content Intelligence",
        [
            "content-weak-language",
            "content-tautological",
            "content-description-routing",
            "content-redundant-with-tooling",
            "content-instruction-budget",
            "content-negative-only",
            "content-section-length",
            "content-contradiction",
            "content-hook-candidate",
            "content-cognitive-chunks",
            "content-embedded-secrets",
            "content-banned-references",
            "content-inconsistent-terminology",
            "content-instruction-drift",
            "content-broken-internal-reference",
            "content-unlinked-internal-reference",
            "content-placeholder-text",
            "content-unclosed-fence",
            "content-repeated-directive",
            "content-emphasis-density",
            "content-missing-stop-condition",
            "content-inline-tool-examples",
            "content-progressive-disclosure",
            "content-mcp-tool-name",
        ],
        "Rules that go beyond structural validation to analyze the *quality* of "
        "instruction files. Built on attention research "
        "([lost-in-the-middle](https://arxiv.org/abs/2307.03172), "
        "[instruction-following limits](https://openreview.net/forum?id=R6q67CDBCH)) "
        "and prompt engineering best practices. See "
        "[docs/designs/content-rules-research.md](docs/designs/content-rules-research.md) "
        "for the full research basis behind each rule.",
    ),
    (
        "Context Budget",
        ["context-budget"],
        "Warns when instruction and configuration files exceed recommended "
        "token limits. Uses a `len(text) / 4` approximation for token counting. "
        "Supports per-category `warn` and `error` thresholds. Disabled by default.",
    ),
    (
        "Copilot / VS Code",
        ["copilot-agent-valid"],
        "Validates target-aware YAML frontmatter in `.github/agents/**/*.md` "
        "and legacy `.github/chatmodes/**/*.chatmode.md`: shared fields, real "
        "booleans, tools and model collections, subagents, handoffs, cloud MCP "
        "servers, metadata, and preview hooks. Embedded MCP and hooks also reach "
        "the shared security and policy rules. Enabled automatically wherever "
        "Copilot or VS Code repository content is detected.",
    ),
    (
        "Cursor",
        ["cursor-rules-valid", "cursor-hooks-valid"],
        "Validates Cursor's repository-shipped configuration under every `.cursor/` "
        "directory in the repository, the root one and any in a monorepo "
        "subpackage: `rules/**/*.mdc` "
        "frontmatter (the fields that decide whether a rule ever activates) and "
        "`.cursor/hooks.json` structure. Cursor reads AGENTS.md for portable "
        "instructions, so no Cursor-specific instruction format is validated. "
        "Enabled automatically wherever a `.cursorrules` file exists, or a "
        "`.cursor/` directory holds Cursor content — `rules/`, `commands/`, "
        "`skills/`, `mcp.json` or `hooks.json`. A `.cursor/` holding only "
        "unrelated files does not activate them.",
    ),
    (
        "Devin",
        ["devin-rules-valid", "devin-skill-valid"],
        "Validates Devin CLI/Desktop workspace rules under `.devin/rules/` "
        "and legacy `.windsurf/rules/`, plus Devin-native `.devin/skills` whose "
        "frontmatter is optional and extends the portable Agent Skills dialect. "
        "Windsurf `.windsurf/skills` use portable Agent Skills validation. Enabled "
        "automatically when Devin repository context is present.",
    ),
    (
        "Grok Build",
        [
            "grok-agent-valid",
            "grok-hooks-valid",
            "grok-marketplace-index-parity",
            "grok-marketplace-json-valid",
            "grok-plugin-json-valid",
            "grok-plugin-structure",
        ],
        "Validates `.grok/hooks/*.json`, the project hooks Grok Build loads and "
        "silently refuses when they are malformed. What a defect costs depends "
        "on where it is: a wrong-typed field or a handler with no `type` "
        "refuses the whole file, an uncompilable matcher drops that group, an "
        "unknown event skips its entries, and a handler with nothing to run "
        "drops that handler — none of it reported, because `grok inspect` "
        "emits no configuration warning for any of them. Grok accepts several "
        "spellings of every event, including Cursor's, so a shared hooks file "
        "is not reported for the spelling it uses. `grok-agent-valid` covers the "
        "other surface Grok refuses in silence: a `.grok/agents/*.md` subagent "
        "missing the `name` or `description` its loader registers it by."
        "\n\nPackaging fails the same way: `grok-plugin-json-valid` reports a "
        "manifest Grok skips the whole plugin directory over while "
        "`grok plugin install` still prints success, `grok-plugin-structure` "
        "reports a directory the installer refuses, "
        "`grok-marketplace-json-valid` reports a catalog Grok discards for "
        "a scan of `plugins/` and entries it drops one at a time, and "
        "`grok-marketplace-index-parity` reports a `plugin-index.json` that "
        "has drifted from the catalog beside it, which blanks what the "
        "marketplace browser shows.\n\nGrok reads AGENTS.md for "
        "portable instructions and portable Agent Skills from `.grok/skills/`, "
        "and its rules, commands and agent prose get the content and security "
        "rules every format shares, so no Grok-specific instruction format "
        "is validated.\n\nThe hooks and subagent rules are enabled automatically "
        "when a `.grok/` project layer exists; the packaging rules when a "
        "`.grok-plugin/` manifest or catalog does.",
    ),
    (
        "Hooks",
        [
            "claude-hooks-valid",
            "hooks-dangerous",
            "hooks-prohibited",
        ],
        "Validates hook configuration. The security rules scan every hook a repository "
        "ships — a Claude plugin's `hooks/hooks.json` and `.claude/settings*.json`, "
        "Codex's `.codex/hooks.json` and plugin hooks, Muse Code's `.muse/hooks.json`, "
        "Grok Build's `.grok/hooks/*.json` and its plugin hooks, Cursor's "
        "`.cursor/hooks.json`, and skill, "
        "Claude-agent, and Copilot-agent frontmatter (`hooks:` key) — for supply-chain "
        "attack patterns (inspired by the "
        "[Shai-Hulud attack](https://safedep.io/mini-shai-hulud-strikes-again-314-npm-packages-compromised/)).",
    ),
    (
        "Instruction Files",
        [
            "instruction-file-valid",
            "instruction-imports-valid",
            "claude-md-agents-import",
        ],
        "Validates AI coding assistant instruction files (AGENTS.md, CLAUDE.md, "
        "GEMINI.md, QWEN.md, and Devin-compatible alternatives). Checks encoding, "
        "non-emptiness, and that supported `@import` references resolve to existing "
        "files. Enabled automatically when one of those files is present.",
    ),
    (
        "MCP (Model Context Protocol)",
        [
            "mcp-valid-json",
            "mcp-prohibited",
            "mcp-registry-server-json-valid",
            "mcp-registry-version-semver",
            "mcp-registry-npm-name-match",
        ],
        "Validates both MCP client configuration and MCP Registry publisher "
        "metadata. Registry rules use every released schema and local "
        "package metadata; they never query a package registry.",
    ),
    (
        "Muse Code",
        ["muse-hooks-valid"],
        "Validates `.muse/hooks.json`, the project hooks Muse Code loads and "
        "silently refuses when they are malformed. What a defect costs "
        "depends on where it is: a wrong-typed handler field rejects the "
        "whole file, a stray key on a matcher group drops that group, an "
        "unknown event skips its entries, and a bad handler drops that "
        "handler — none of it reported in a headless run. Muse's handler "
        "fields are a subset of Claude Code's, so a hooks file copied from "
        "`.claude/` is the usual way in. Muse reads AGENTS.md for portable "
        "instructions and the shared `.agents/memory/` convention for "
        "committed project memory; both get the content and security rules "
        "every format shares, so no Muse-specific instruction format is "
        "validated. Enabled automatically when a `.muse/hooks.json` exists.",
    ),
    (
        "OpenAI Codex",
        [
            "codex-hooks-valid",
            "codex-openai-metadata",
            "codex-plugin-json-valid",
            "codex-plugin-structure",
            "codex-marketplace-json-valid",
            "codex-marketplace-registration",
        ],
        "Validates OpenAI's optional "
        "[skill metadata](https://learn.chatgpt.com/docs/build-skills#optional-metadata) "
        "in `agents/openai.yaml`, plus Codex plugins and marketplaces against "
        "the [Codex plugin specification]"
        "(https://developers.openai.com/plugins/build/plugins). The metadata "
        "rule auto-enables for Agent Skills; the plugin and marketplace rules "
        "auto-enable only when their Codex manifests are present.",
    ),
    (
        "OpenClaw",
        ["openclaw-metadata"],
        "Validates `metadata.openclaw` in SKILL.md frontmatter against the "
        "[OpenClaw spec](https://docs.openclaw.ai/tools/skills). Only fires "
        "when `metadata.openclaw` is present.",
    ),
    (
        "OpenCode",
        ["opencode-config-valid"],
        "Validates the OpenCode project config — `opencode.json` or "
        "`opencode.jsonc`, at the "
        "repository root or under any `.opencode/` directory — where a "
        "misspelled key is read, ignored and never reported. OpenCode 2.0 "
        "renames much of the schema while still loading the 1.x spelling, so "
        "**both vocabularies are accepted**. OpenCode merges `agent`/`agents` "
        "and `command`/`commands` by entry name; only conflicting definitions "
        "of one name are reported. Comments and trailing commas "
        "are fine — OpenCode reads `.json` through a JSONC parser. OpenCode "
        "reads AGENTS.md for portable instructions, so no OpenCode-specific "
        "instruction format is validated. Its commands, agents, skills and "
        "repository-local files matched by `instructions` paths or globs get the shared content "
        "rules; remote URLs are not fetched. Enabled automatically wherever an "
        "`opencode.json` or `opencode.jsonc` exists, or a `.opencode/` "
        "directory holds OpenCode "
        "content.",
    ),
    (
        "Promptfoo Evals",
        ["promptfoo-valid", "promptfoo-assertions", "promptfoo-metadata"],
        "Validates [promptfoo](https://www.promptfoo.dev/) eval YAML configs "
        "found in `evals/` directories of plugins and skills. "
        "`promptfoo-valid` auto-enables when eval files are detected; "
        "`promptfoo-assertions` and `promptfoo-metadata` are opt-in policy rules.",
    ),
    (
        "Security",
        [
            "security-invisible-unicode",
            "security-hidden-instructions",
            "security-encoded-payload",
            "security-dynamic-context",
        ],
        "Content-validation rules that catch payloads and instructions "
        "invisible to human review: invisible/bidi unicode smuggling, agent "
        "directives hidden in HTML comments or Markdown link labels, and "
        "long high-entropy base64/hex blobs or unallowlisted dynamic-context "
        "commands in agent content that can smuggle or execute payloads.",
    ),
    (
        "Vercel",
        ["skills-lock-valid"],
        "Validates every `skills-lock.json` written by the "
        "[Vercel skills CLI](https://github.com/vercel-labs/skills): strict JSON, "
        "the versioned project-lock shape, required source metadata, digest syntax, "
        "and paths that remain portable across machines. Lockfiles are discovered "
        "recursively for monorepos and the rule auto-enables when one is present.",
    ),
    (
        "Deprecated",
        [
            "content-critical-position",
            "content-actionability-score",
            "skill-frontmatter",
        ],
        "These rules are deprecated and will be removed in a future release. "
        "They no longer run under `enabled: auto`; set `enabled: true` in "
        "`.skillsaw.yaml` to keep running one during the transition. The "
        "content rules encoded attention-era heuristics that newer models no "
        "longer need; `skill-frontmatter` is replaced by `agentskill-valid`.",
    ),
]


def _table_cell(text):
    """Escape characters that would break a markdown table cell."""
    return str(text).replace("|", "\\|")


def _heading_to_anchor(heading_text):
    """Convert a markdown heading to a GitHub-style anchor link."""
    anchor = heading_text.lower()
    anchor = re.sub(r"[^\w\s-]", "", anchor)
    anchor = re.sub(r"\s+", "-", anchor.strip())
    return anchor


def _generate_toc(readme_text):
    """Parse all ## and ### headings outside generated blocks and build a TOC."""
    lines = readme_text.split("\n")
    toc = []
    in_generated = False
    in_code_block = False
    in_html_block = False

    for line in lines:
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        stripped = line.strip()
        if re.match(r"<table[\s>]", stripped, re.IGNORECASE):
            in_html_block = True
        if in_html_block:
            if re.search(r"</table>", stripped, re.IGNORECASE):
                in_html_block = False
            continue
        if BEGIN_MARKER in line or TOC_BEGIN in line:
            in_generated = True
            continue
        if END_MARKER in line or TOC_END in line:
            in_generated = False
            continue
        if in_generated:
            continue

        m = re.match(r"^(#{2,3})\s+(.+)$", line)
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2).strip()
        display = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        if display == "Table of Contents":
            continue
        anchor = _heading_to_anchor(display)
        indent = "  " * (level - 2)
        toc.append(f"{indent}- [{display}](#{anchor})")

    return "\n".join(toc)


def main():
    readme_path = Path(__file__).resolve().parent.parent / "README.md"
    readme = readme_path.read_text()

    has_begin = BEGIN_MARKER in readme
    has_end = END_MARKER in readme
    if not has_begin and not has_end:
        print("README.md has no generated rules section; skipping README update.")
        sys.exit(0)
    if has_begin != has_end:
        print(
            f"ERROR: Mismatched markers in README.md (begin: {has_begin}, end: {has_end})",
            file=sys.stderr,
        )
        sys.exit(1)

    rules_by_id = {}
    for rule_class in BUILTIN_RULES:
        rule = rule_class()
        rules_by_id[rule.rule_id] = rule

    # Every builtin rule must be documented in a group — fail loudly when
    # a new rule is missing so it can't silently drop out of the README.
    grouped_ids = [rid for _, rids, _ in RULE_GROUPS for rid in rids]
    missing = sorted(set(rules_by_id) - set(grouped_ids))
    if missing:
        print(f"ERROR: rules missing from RULE_GROUPS: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    defaults = LinterConfig.default()

    lines = []

    for group_name, rule_ids, description in RULE_GROUPS:
        lines.append(f"### {group_name}")
        lines.append("")
        if description:
            lines.append(description)
            lines.append("")

        lines.append("| Rule ID | Description | Default Severity | Autofix |")
        lines.append("|---------|-------------|------------------|---------|")

        params_sections = []

        for rule_id in rule_ids:
            rule = rules_by_id[rule_id]
            rule_config = defaults.rules.get(rule_id, {})
            enabled = rule_config.get("enabled", True)
            severity = rule_config.get("severity") or rule.default_severity().value

            if rule.deprecated is not None:
                severity_str = f"{severity} (deprecated)"
            elif enabled == "auto":
                severity_str = f"{severity} (auto)"
            elif enabled is False:
                severity_str = f"{severity} (disabled)"
            else:
                severity_str = severity

            fix_str = "auto" if rule.supports_autofix else "-"

            description = rule.description
            if rule.aliases:
                former = ", ".join(f"`{a}`" for a in rule.aliases)
                description = f"{description} (formerly {former})"

            lines.append(
                f"| `{rule_id}` | {_table_cell(description)} | {severity_str} | {fix_str} |"
            )

            if rule.config_schema:
                params_sections.append((rule_id, rule.config_schema))

        lines.append("")

        for rule_id, schema in params_sections:
            lines.append(f"**`{rule_id}` parameters:**")
            lines.append("")
            lines.append("| Parameter | Description | Default |")
            lines.append("|-----------|-------------|---------|")
            for param_name, param_info in schema.items():
                desc = _table_cell(param_info["description"])
                default = f"`{json.dumps(param_info['default'])}`"
                lines.append(f"| `{param_name}` | {desc} | {default} |")
            lines.append("")

    generated = "\n".join(lines).rstrip()

    before = readme[: readme.index(BEGIN_MARKER) + len(BEGIN_MARKER)]
    after = readme[readme.index(END_MARKER) :]
    readme = f"{before}\n\n{generated}\n\n{after}"

    if TOC_BEGIN in readme and TOC_END in readme:
        toc = _generate_toc(readme)
        before_toc = readme[: readme.index(TOC_BEGIN) + len(TOC_BEGIN)]
        after_toc = readme[readme.index(TOC_END) :]
        readme = f"{before_toc}\n\n{toc}\n\n{after_toc}"

    readme_path.write_text(readme)
    print("Updated README.md with generated rules documentation and TOC.")


if __name__ == "__main__":
    main()
