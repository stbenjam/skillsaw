---
name: {{AGENT_NAME}}
description: "Specialized agent for {{AGENT_NAME}} tasks. Replace this description with the agent's purpose and when to invoke it."
subagent_type: {{AGENT_ID}}
---

# {{AGENT_NAME}}

Use this section to define the agent's purpose — update it with what the
agent does and how to verify its output.

## When to Use

Use this agent when you need to:

- Run a {{AGENT_NAME}} task that benefits from focused context
- Update this list with the concrete scenarios the agent handles

## Capabilities

Update this list with the tools the agent uses:

- Read and write files with the `Read` and `Edit` tools
- Run searches with `Grep` and analyze the results

## How to Use

```text
Use the Task tool to launch this agent:
- subagent_type: "{{AGENT_ID}}"
- prompt: Detailed task description
```

## Examples

### Example 1: Run a Basic Task
```yaml
subagent_type: "{{AGENT_ID}}"
prompt: "Describe the task for the agent to perform"
```
