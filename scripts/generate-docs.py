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
        "`.claude/` directories, Codex plugins and marketplaces, and Agent "
        "Plugin packages.",
    ),
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
        "OpenAI Codex",
        [
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
        "Hooks",
        [
            "hooks-json-valid",
            "hooks-dangerous",
            "hooks-prohibited",
        ],
        "Validates hook configuration. The security rules scan hooks in "
        "`hooks.json`, `.cursor/hooks.json`, `.claude/settings*.json`, and "
        "skill/agent frontmatter (`hooks:` key) for supply-chain "
        "attack patterns (inspired by the "
        "[Shai-Hulud attack](https://safedep.io/mini-shai-hulud-strikes-again-314-npm-packages-compromised/)).",
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
        "MCP (Model Context Protocol)",
        ["mcp-valid-json", "mcp-prohibited"],
        None,
    ),
    (
        "OpenClaw",
        ["openclaw-metadata"],
        "Validates `metadata.openclaw` in SKILL.md frontmatter against the "
        "[OpenClaw spec](https://docs.openclaw.ai/tools/skills). Only fires "
        "when `metadata.openclaw` is present.",
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
        "Instruction Files",
        ["instruction-file-valid", "instruction-imports-valid"],
        "Validates AI coding assistant instruction files (AGENTS.md, CLAUDE.md, "
        "GEMINI.md, QWEN.md) at the repository root. Checks encoding, non-emptiness, "
        "and that `@import` references resolve to existing files. Enabled automatically when one of those files is present.",
    ),
    (
        "Context Budget",
        ["context-budget"],
        "Warns when instruction and configuration files exceed recommended "
        "token limits. Uses a `len(text) / 4` approximation for token counting. "
        "Supports per-category `warn` and `error` thresholds. Disabled by default.",
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
        "CodeRabbit",
        ["coderabbit-yaml-valid", "coderabbit-schema-valid"],
        "Validates `.coderabbit.yaml` config files for YAML syntax. "
        "Instruction text fields (`reviews.instructions`, per-path "
        "instructions, per-tool instructions, `chat.instructions`) are "
        "automatically checked by the content-* rules above. Auto-enabled "
        "when `.coderabbit.yaml` is detected.",
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
        "APM (Agent Package Manager)",
        ["apm-yaml-valid", "apm-structure-valid"],
        "Validates repositories using the [APM](https://github.com/microsoft/apm) "
        "directory layout (`.apm/`). Auto-enables when `.apm/` is detected.",
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
