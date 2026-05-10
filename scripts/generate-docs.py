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
            "content-critical-position",
            "content-redundant-with-tooling",
            "content-instruction-budget",
            "content-negative-only",
            "content-section-length",
            "content-contradiction",
            "content-hook-candidate",
            "content-actionability-score",
            "content-cognitive-chunks",
            "content-embedded-secrets",
            "content-banned-references",
            "content-inconsistent-terminology",
        ],
        "Rules that go beyond structural validation to analyze the *quality* of "
        "instruction files. Built on attention research "
        "([lost-in-the-middle](https://arxiv.org/abs/2307.03172), "
        "[instruction-following limits](https://openreview.net/forum?id=R6q67CDBCH)) "
        "and prompt engineering best practices. All support LLM-powered fixes via "
        "`--fix --llm`. See "
        "[docs/designs/content-rules-research.md](docs/designs/content-rules-research.md) "
        "for the full research basis behind each rule.",
    ),
    (
        "CodeRabbit",
        ["coderabbit-yaml-valid"],
        "Validates `.coderabbit.yaml` config files for YAML syntax. "
        "Instruction text fields (`reviews.instructions`, per-path "
        "instructions, per-tool instructions, `chat.instructions`) are "
        "automatically checked by the content-* rules above. Auto-enabled "
        "when `.coderabbit.yaml` is detected.",
    ),
    (
        "APM (Agent Package Manager)",
        ["apm-yaml-valid", "apm-structure-valid"],
        "Validates repositories using the [APM](https://github.com/microsoft/apm) "
        "directory layout (`.apm/`). Auto-enables when `.apm/` is detected.",
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

        lines.append("| Rule ID | Description | Default Severity | Autofix |")
        lines.append("|---------|-------------|------------------|---------|")

        params_sections = []

        for rule_id in rule_ids:
            rule = rules_by_id[rule_id]
            rule_config = defaults.rules.get(rule_id, {})
            enabled = rule_config.get("enabled", True)
            severity = rule_config.get("severity", rule.default_severity().value)

            if enabled == "auto":
                severity_str = f"{severity} (auto)"
            elif enabled is False:
                severity_str = f"{severity} (disabled)"
            else:
                severity_str = severity

            fix_types = []
            if rule.supports_autofix:
                fix_types.append("auto")
            if rule.llm_fix_prompt is not None:
                fix_types.append("llm")
            fix_str = ", ".join(fix_types) if fix_types else "-"

            lines.append(f"| `{rule_id}` | {rule.description} | {severity_str} | {fix_str} |")

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
