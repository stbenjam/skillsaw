The official MCP Registry verifies npm package ownership with the `mcpName`
field in `package.json`. It must exactly match the server `name` in
`server.json`, as documented in the Registry's
[npm package requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx#npm-packages).

## What is checked

For every `packages[]` entry whose `registryType` is `npm`, the rule matches local
`package.json` files by package `identifier` (and matching `version` when declared)
and verifies that:

- `package.json` declares a string-valued `mcpName`; and
- `mcpName` matches the exact `server.json` `name`, including case.


This check operates entirely offline on local files; external or remote dependencies
without local manifests are not flagged.


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
