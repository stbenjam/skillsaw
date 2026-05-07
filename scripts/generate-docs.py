#!/usr/bin/env python3
"""Generate the Builtin Rules section of README.md from rule metadata."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from skillsaw.rules.builtin import BUILTIN_RULES
from skillsaw.config import LinterConfig

BEGIN_MARKER = "<!-- BEGIN GENERATED RULES -->"
END_MARKER = "<!-- END GENERATED RULES -->"

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
]


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
                default = f'`{param_info["default"]}`'
                lines.append(f"| `{param_name}` | {desc} | {default} |")
            lines.append("")

    generated = "\n".join(lines).rstrip()

    before = readme[: readme.index(BEGIN_MARKER) + len(BEGIN_MARKER)]
    after = readme[readme.index(END_MARKER) :]
    new_readme = f"{before}\n\n{generated}\n\n{after}"

    readme_path.write_text(new_readme)
    print("Updated README.md with generated rules documentation.")


if __name__ == "__main__":
    main()
