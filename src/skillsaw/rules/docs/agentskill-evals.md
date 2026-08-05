## Why

The Agent Skills evaluation guide describes an `evals/evals.json` convention.
The formal Agent Skills specification does not define evaluation files or make
this layout part of skill validity. When a project adopts the guide convention,
malformed JSON or an incompatible structure prevents tooling for that convention
from using it reliably. The violation message distinguishes "valid JSON in a
different format" from a syntax error.

## Examples

**Bad (valid JSON, but not the evals format):**

```json
[{"id": "case-1", "question": "Deploy to staging"}]
```

**Good:**

```json
{
  "skill_name": "deployment-helper",
  "evals": [
    {
      "id": 1,
      "prompt": "Deploy the application to staging",
      "expected_output": "A safe staging deployment plan",
      "files": [],
      "assertions": ["The response includes a rollback step"]
    }
  ]
}
```

## How to fix

Provide a top-level `evals` array. skillsaw expects each case to have a numeric
`id` and string `prompt`, with optional `expected_output`, `files`, and
`assertions`; `skill_name` may name the skill being evaluated. To opt out of
the convention:

```yaml
rules:
  agentskill-evals:
    enabled: false
```

See the Agent Skills guide on
[evaluating skills](https://agentskills.io/skill-creation/evaluating-skills).
