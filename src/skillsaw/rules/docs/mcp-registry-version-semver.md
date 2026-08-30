Released MCP Registry schemas permit non-semantic server versions, but warn
that they may not sort predictably. This rule recommends strict
[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) for the
top-level `server.json` `version`.

This is a warning, not a validity error. Exact non-semantic versions remain
allowed by the official schema. Forbidden tags and ranges are reported by
`mcp-registry-server-json-valid` instead, so one value does not produce two
findings.

## What is checked

Accepted versions contain numeric major, minor, and patch components without
leading zeroes. Optional prerelease and build identifiers follow SemVer 2.0.0:

```text
1.2.3
1.2.3-beta.1
1.2.3-beta.1+build.4
```

Versions such as `v1.2.3`, `1.2`, `2025-12-11`, and `1.2.3-01` trigger the
recommendation.

## How to fix

Publish a three-component semantic version. When the upstream package
ecosystem uses a different version scheme intentionally, configure this rule
off or lower its severity rather than treating the valid Registry document as
broken.
