# kiro-agent-valid

Check the documented shared subset of Kiro JSON and Markdown agent configuration.
This rule is opt-in. It reports invalid syntax and incorrect types for common
metadata, tool-selector lists, inclusion flags, and resource/MCP containers.

## How to fix

Use JSON objects for `.kiro/agents/**/*.json`, or YAML frontmatter and a Markdown
prompt body for `.kiro/agents/**/*.md`. Use strings for names, descriptions,
models and JSON prompts; arrays for tool selectors and resources; and booleans
for inclusion flags. Resource objects remain accepted without deeper validation.

Legacy CLI 2.x permission fields and current V3 `permissions` are not validated
or migrated. Unknown fields are accepted. Hooks and Powers are outside this rule.
See the [Kiro support boundaries](../kiro.md) for formats, versions and sources.
