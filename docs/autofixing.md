# Autofixing

skillsaw supports two levels of autofixing — deterministic fixes for structural issues and LLM-powered fixes for content quality. Coding agents (Claude Code, Cursor, etc.) are also fully capable of working with skillsaw directly — the lint interface is familiar, and every violation points to `skillsaw explain` which includes how-to-fix guidance. Rules declare which fix types they support (see the **Autofix** column in the [rules reference](rules/index.md)).

## Deterministic Fixes

Safe, pattern-based fixes that run instantly without any external dependencies:

```bash
skillsaw fix                     # Apply safe structural fixes
skillsaw fix --suggest           # Also apply suggested fixes (e.g. stale references)
skillsaw fix --dry-run           # Preview safe fixes as colored diffs without writing
skillsaw fix --suggest --dry-run # Preview safe + suggested fixes
```

Examples: adding missing frontmatter, renaming files to kebab-case, registering unregistered plugins in marketplace.json, fixing skill names to match directory names. These are marked **SAFE** confidence and applied automatically.

Some fixes produce cascading changes — for example, renaming a skill name creates stale references in other files. These secondary fixes are marked **SUGGEST** confidence because simple name matching may replace occurrences that aren't actually skill name references. Use `--suggest --dry-run` to review these changes before applying them.

## Working with Coding Agents

If you're already working in a coding agent (Claude Code, Cursor, etc.), you don't need any extra setup — the agent can read skillsaw's lint output and fix violations directly. skillsaw is a standard linter, so agents treat it the same way they treat ESLint or ruff: run it, read the output, fix what it flags. Every violation points to `skillsaw explain <rule-id>`, which provides detailed how-to-fix guidance that agents invoke automatically.

The [onboarding skill](getting-started.md#onboard-with-ai) uses this approach end-to-end — it lints, applies deterministic fixes, then has your agent resolve the remaining violations interactively.

## LLM-Powered Fixes

For batch fixing without a coding agent — in CI, scripted workflows, or when you want a one-command fix pass — skillsaw includes a built-in LLM fix path via [LiteLLM](https://docs.litellm.ai/docs/providers). This is an optional dependency, not installed by default.

Most content intelligence rules support these fixes (see the **Autofix** column in the [rules reference](rules/index.md)). The LLM reads your instruction files, rewrites violations, and re-lints in a loop until the file is clean — or rolls back if it made things worse.

```bash
skillsaw fix --llm                          # Fix with default model
skillsaw fix --llm --model vertex_ai/claude-sonnet-4-6
skillsaw fix --llm --model openrouter/minimax/minimax-m1
skillsaw fix --llm --all                    # Include info-level violations
skillsaw fix --llm --workers 8              # Parallel workers (default: 4)
skillsaw fix --llm --max-iterations 10      # Max iterations per file
skillsaw fix --llm --dry-run                # Preview changes without writing
skillsaw fix --llm -y                       # Auto-apply without confirmation
```

### How it works

1. skillsaw lints your repo and groups violations by file
2. Each lint-tree node is sent to an LLM agent with scoped tools for reading, editing, linting, and diffing
3. The LLM iteratively edits and re-lints until violations are resolved
4. After the LLM finishes, skillsaw compares violation counts — if a file got worse, it's rolled back to the original
5. Files are processed in parallel with a live progress bar showing ETA

Use `--dry-run` to review all proposed changes as unified diffs before committing to them.

Check `skillsaw list-rules` to see which rules support `auto`, `llm`, or both fix types.

!!! warning "Deprecation"
    `skillsaw lint --fix` is deprecated and will be removed in 1.0. Use `skillsaw fix` instead.

## LLM Setup

skillsaw uses [LiteLLM](https://docs.litellm.ai/docs/providers) under the hood, so any LiteLLM-compatible model works. Model names follow the LiteLLM `provider/model` format.

### Providers

Install the extras for your provider and set the required environment variables:

=== "Anthropic"

    ```bash
    pip install 'skillsaw[llm]'
    export ANTHROPIC_API_KEY=sk-ant-...
    skillsaw fix --llm --model claude-sonnet-4-6
    ```

=== "Vertex AI"

    ```bash
    pip install 'skillsaw[vertexai]'
    gcloud auth application-default login
    export VERTEXAI_PROJECT=my-gcp-project
    export VERTEXAI_LOCATION=global
    skillsaw fix --llm --model vertex_ai/claude-sonnet-4-6
    ```

=== "AWS Bedrock"

    ```bash
    pip install 'skillsaw[bedrock]'
    export AWS_ACCESS_KEY_ID=...
    export AWS_SECRET_ACCESS_KEY=...
    export AWS_REGION_NAME=us-east-1
    skillsaw fix --llm --model bedrock/anthropic.claude-sonnet-4-6-20250514-v1:0
    ```

=== "OpenAI"

    ```bash
    pip install 'skillsaw[llm]'
    export OPENAI_API_KEY=sk-...
    skillsaw fix --llm --model openai/gpt-4o
    ```

=== "OpenRouter"

    ```bash
    pip install 'skillsaw[llm]'
    export OPENROUTER_API_KEY=...
    skillsaw fix --llm --model openrouter/anthropic/claude-sonnet-4-6
    ```

To avoid passing `--model` every time, set it in your environment or config:

```bash
export SKILLSAW_MODEL=claude-sonnet-4-6
```

```yaml
# .skillsaw.yaml
llm:
  model: claude-sonnet-4-6
```

### Environment Variables Reference

| Provider | Environment Variables |
|----------|----------------------|
| Vertex AI | `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION` (+ `gcloud auth application-default login`) |
| Anthropic | `ANTHROPIC_API_KEY` |
| AWS Bedrock | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` |
| OpenAI | `OPENAI_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |

See the [LiteLLM provider documentation](https://docs.litellm.ai/docs/providers) for the full list of supported providers.
