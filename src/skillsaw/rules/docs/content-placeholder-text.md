## Why

An LLM cannot distinguish between a deliberate instruction and an
unfilled template. A `TODO`, `[Insert API key here]`, or `*TBD*` left
in an instruction file will be interpreted literally — the model may
try to complete the TODO itself, use a placeholder value as a real
credential, or follow a half-written instruction in unpredictable ways.

## Examples

**Bad:**

```markdown
TODO: add deployment instructions here.
Set the API key to [Insert your API key].
*Details to be added*
```

**Good:**

```markdown
Deploy with `make deploy-staging`.
Set the API key via the `API_KEY` environment variable.
```

## How to fix

Replace each placeholder with the real content it was standing in for.
If the content is not ready yet, remove the placeholder entirely —
an absent instruction is better than one the model will misinterpret.
