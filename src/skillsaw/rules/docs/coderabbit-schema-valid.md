## Why

CodeRabbit's configuration schema (`schema.v2.json`) is a *closed* object
(`additionalProperties: false`): only a fixed set of top-level keys is
recognized. A misspelled top-level key — `review` instead of `reviews`,
`knowledge_base` typo'd, etc. — is silently ignored, so that whole block of
configuration reverts to defaults without any error. Likewise, `reviews.profile`
accepts only a fixed set of values; a typo there is ignored.

This rule flags **near-miss** unknown top-level keys (likely typos) and invalid
`reviews.profile` values. Unfamiliar keys that are not close to any known key are
left alone, so a genuinely new CodeRabbit option never produces a false positive.

## Examples

**Bad:**

```yaml
review:            # typo — CodeRabbit expects `reviews`
  profile: agressive   # typo — not a valid profile
```

**Good:**

```yaml
reviews:
  profile: assertive
```

## How to fix

Correct the key to the suggested name (`reviews`, `chat`, `knowledge_base`,
`code_generation`, `language`, `tone_instructions`, `early_access`,
`enable_free_tier`, `inheritance`, `issue_enrichment`). For `reviews.profile`,
use one of `assertive`, `chill`, or `quiet`. See the
[CodeRabbit configuration reference](https://docs.coderabbit.ai/reference/configuration).
