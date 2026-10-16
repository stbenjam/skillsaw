Validates `.ruler/ruler.toml` against the configuration shape in Ruler 0.3.44.
The check is opt-in. Rule Markdown is plain instruction prose, so this check
does not require frontmatter on `.ruler/**/*.md`.

## How to fix

Correct TOML syntax and use the types accepted by the pinned configuration
schema. `default_agents` is an array of strings; `nested` and the control flags
are booleans. `agents` contains reserved control flags alongside per-agent
configuration tables. Unknown configuration keys are rejected by that release.
MCP server definitions are tables, without a hardcoded model or target registry.

Run Ruler explicitly after editing its sources, then lint the output using the
consumer rules. This rule does not execute Ruler, validate remote endpoints, or
prove that emitted files are valid for their target.

See the [generator workflow](https://skillsaw.org/generators/) for pinned evidence,
copy attribution, supported layouts, and reproduction commands.
