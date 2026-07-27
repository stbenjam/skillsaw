## Why

The formal Agent Skills specification permits arbitrary directories. This
disabled-by-default rule is an optional packaging policy for repositories that
want to limit skill-root directories to a configured allowlist. Its defaults
cover common Agent Skills directories and the evaluation-guide `evals/`
convention. OpenAI's `agents/` host-metadata directory is accepted separately;
it is not repository-authored package content governed by this policy.

## Examples

**Bad:**

```
my-skill/
  SKILL.md
  helpers/       # not allowed by this project's configured policy
  test-data/     # not allowed by this project's configured policy
```

**Good:**

```
my-skill/
  SKILL.md
  evals/
  references/
```

## How to fix

Move files into one of the configured directories, add the intentional
directory to `allowed_dirs`, or disable this opt-in rule.
