The official MCP Registry verifies npm package ownership with the `mcpName`
field in `package.json`. It must exactly match the server `name` in
`server.json`, as documented in the Registry's
[npm package requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx#npm-packages).

## What is checked

For every `packages[]` entry whose `registryType` is `npm`, the rule looks
for a local `package.json` whose `name` matches the package `identifier`. When
the Registry entry declares `version`, the local manifest's `version` must
also match exactly before the rule treats it as that published release. It
supports a package beside `server.json` and packages elsewhere in a monorepo.
The matching local manifest must:

- be valid strict JSON;
- declare a string-valued `mcpName`; and
- set `mcpName` to the exact `server.json` `name`, including case.

The check is intentionally local-only. A published npm dependency may live in
another repository, so the absence of a matching local `package.json` is not
a violation. Skillsaw never downloads npm metadata.

## How to fix

Add the Registry name to the package that the npm identifier names:

```json
{
  "name": "@example/weather-mcp",
  "version": "1.0.0",
  "mcpName": "io.github.example/weather"
}
```

Publish a new package version after changing this metadata; the live Registry
checks the metadata of the package version named by `server.json`.
