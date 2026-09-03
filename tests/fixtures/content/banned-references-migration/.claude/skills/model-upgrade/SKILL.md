---
name: model-upgrade
description: Move a service off retired Anthropic and OpenAI model ids onto their current replacements. Use when a provider announces a retirement or an API call returns a deprecation notice.
---

# Model upgrade

A retired model id keeps answering for a few months and then stops. This
skill finds every pinned id in the repository and rewrites it.

## Replacement table

Each row retires the id on the left in favour of the id on the right.

| Retired id | Retired on | Replacement |
| --- | --- | --- |
| `claude-2.1` | 2025-07-21 | `claude-sonnet-5` |
| `claude-3-opus-20240229` | 2026-01-05 | `claude-opus-4-8` |
| `gpt-3.5-turbo` | 2026-02-13 | `gpt-5-mini` |

## Rewrite the pinned ids

Run the rewriter over the source tree. It only touches ids the table
above covers, so an id it does not know is left alone for a human.

```python
MODEL_MIGRATIONS = {
    "claude-2": "claude-sonnet-5",
    "claude-3-haiku": "claude-haiku-4-5",
    "gpt-3.5-turbo": "gpt-5-mini",
}


def migrate(model: str) -> str:
    """Return the current id for a retired one, or the id unchanged."""
    return MODEL_MIGRATIONS.get(model, model)
```

## Check the deployment configs

The rewriter reads Python only, so deployment YAML needs a second pass.
A staging config that still pins a retired id looks like this:

```yaml
service: summarizer
model: claude-2
max_tokens: 4096
```

Point it at `claude-sonnet-5` and redeploy before the retirement date.

## Routing tables go stale too

A router that still names retired ids is the most common leftover, and
it survives a rewrite because the ids sit in a table rather than in
code:

| Request kind | Model | Fallback |
| --- | --- | --- |
| Short answers | `claude-3-haiku` | `claude-3-opus` |
| Long context | `claude-3.5-sonnet` | `claude-3-opus` |

Every id in that table is retired. Replace them with the current ids
from the replacement table, then delete the fallback column — the
provider routes around a busy model on its own.
