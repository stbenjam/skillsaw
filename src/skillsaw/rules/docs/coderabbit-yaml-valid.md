## Why

`.coderabbit.yaml` configures CodeRabbit's review behavior, including
custom instructions that are fed to the LLM. Invalid YAML means the
entire configuration is ignored and CodeRabbit falls back to defaults
— your custom review instructions and path-specific rules are silently
lost.

## Examples

**Bad:**

```yaml
reviews:
  instructions: "Be strict
    about error handling
```

**Good:**

```yaml
reviews:
  instructions: |
    Be strict about error handling.
    Flag any function that swallows exceptions.
```

## How to fix

Fix the YAML syntax error at the line reported in the violation. Common
issues: unquoted strings with special characters, incorrect indentation,
and missing closing quotes. Use a YAML linter or validator to check the
file before committing.
