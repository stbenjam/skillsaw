#!/usr/bin/env python3
"""Generate the Builtin Rules section and Table of Contents of README.md."""

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
            "agentskill-description",
            "agentskill-structure",
            "agentskill-evals",
            "agentskill-evals-required",
        ],
        "These rules validate skills against the [agentskills.io specification]"
        "(https://agentskills.io/specification). They auto-enable for agentskills "
        "repos, single plugins, and marketplaces whenever skills are detected.",
    ),
    (
        "Plugin Structure",
        ["plugin-json-required", "plugin-json-valid", "plugin-naming", "plugin-readme"],
        None,
    ),
    (
        "Command Format",
        ["command-naming", "command-frontmatter", "command-sections", "command-name-format"],
        None,
    ),
    (
        "Marketplace",
        ["marketplace-json-valid", "marketplace-registration"],
        None,
    ),
    (
        "Skills, Agents, Hooks",
        ["skill-frontmatter", "agent-frontmatter", "hooks-json-valid"],
        None,
    ),
    (
        "MCP (Model Context Protocol)",
        ["mcp-valid-json", "mcp-prohibited"],
        None,
    ),
    (
        "Rules Directory",
        ["rules-valid"],
        None,
    ),
    (
        "Openclaw",
        ["openclaw-metadata"],
        "Validates `metadata.openclaw` in SKILL.md frontmatter against the "
        "[openclaw spec](https://docs.openclaw.ai/tools/skills). Only fires "
        "when `metadata.openclaw` is present.",
    ),
    (
        "Instruction Files",
        ["instruction-file-valid", "instruction-imports-valid"],
        "Validates AI coding assistant instruction files (AGENTS.md, CLAUDE.md, "
        "GEMINI.md) at the repository root. Checks encoding, non-emptiness, and "
        "that `@import` references resolve to existing files. Disabled by default.",
    ),
    (
        "AGENTS.md Deep Validation",
        [
            "agents-md-structure",
            "agents-md-size-limit",
            "agents-md-override-semantics",
            "agents-md-hierarchy-consistency",
            "agents-md-dead-file-refs",
            "agents-md-dead-command-refs",
            "agents-md-weak-language",
            "agents-md-negative-only",
            "agents-md-section-length",
            "agents-md-structure-deep",
            "agents-md-tautological",
            "agents-md-critical-position",
            "agents-md-hook-candidate",
        ],
        "Deep validation for AGENTS.md files (used by OpenAI Codex and GitHub "
        "Copilot coding agent). Checks size limits, override semantics, hierarchy "
        "consistency, dead references, weak language, structure quality, and more. "
        "Auto-enabled when AGENTS.md is detected.",
    ),
    (
        "Context Budget",
        ["context-budget"],
        "Warns when instruction and configuration files exceed recommended "
        "token limits. Uses a `len(text) / 4` approximation for token counting. "
        "Supports per-category `warn` and `error` thresholds. Disabled by default.",
    ),
    (
        "Cursor Rules",
        [
            "cursor-mdc-valid",
            "cursor-rules-deprecated",
            "cursor-mdc-frontmatter",
            "cursor-activation-type",
            "cursor-crlf-detection",
            "cursor-glob-valid",
            "cursor-empty-body",
            "cursor-description-quality",
            "cursor-glob-overlap",
            "cursor-rule-size",
            "cursor-frontmatter-types",
            "cursor-duplicate-rules",
            "cursor-always-apply-overuse",
        ],
        "Validates Cursor IDE `.cursor/rules/*.mdc` files (YAML frontmatter + "
        "Markdown content) and warns about the deprecated `.cursorrules` file. "
        "The monolithic rules (`cursor-mdc-valid`, `cursor-rules-deprecated`) are "
        "disabled by default. The 11 focused rules auto-enable when `.cursor/` "
        "is present and include autofixes for common issues.",
    ),
    (
        "Kiro Steering",
        ["kiro-steering-valid"],
        "Validates Kiro IDE `.kiro/steering/*.md` files (YAML frontmatter with "
        "inclusion modes, fileMatchPattern globs, and auto-mode metadata). "
        "Disabled by default.",
    ),
]


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

    if BEGIN_MARKER not in readme or END_MARKER not in readme:
        print(f"ERROR: Missing markers in README.md", file=sys.stderr)
        print(f"  Expected: {BEGIN_MARKER}", file=sys.stderr)
        print(f"  Expected: {END_MARKER}", file=sys.stderr)
        sys.exit(1)

    rules_by_id = {}
    for rule_class in BUILTIN_RULES:
        rule = rule_class()
        rules_by_id[rule.rule_id] = rule

    defaults = LinterConfig.default()

    lines = []

    for group_name, rule_ids, description in RULE_GROUPS:
        lines.append(f"### {group_name}")
        lines.append("")
        if description:
            lines.append(description)
            lines.append("")

        lines.append("| Rule ID | Description | Default Severity |")
        lines.append("|---------|-------------|------------------|")

        params_sections = []

        for rule_id in rule_ids:
            rule = rules_by_id[rule_id]
            rule_config = defaults.rules.get(rule_id, {})
            enabled = rule_config.get("enabled", True)
            severity = rule.default_severity().value

            if enabled == "auto":
                severity_str = f"{severity} (auto)"
            elif enabled is False:
                severity_str = f"{severity} (disabled)"
            else:
                severity_str = severity

            lines.append(f"| `{rule_id}` | {rule.description} | {severity_str} |")

            if rule.config_schema:
                params_sections.append((rule_id, rule.config_schema))

        lines.append("")

        for rule_id, schema in params_sections:
            lines.append(f"**`{rule_id}` parameters:**")
            lines.append("")
            lines.append("| Parameter | Description | Default |")
            lines.append("|-----------|-------------|---------|")
            for param_name, param_info in schema.items():
                desc = param_info["description"]
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
