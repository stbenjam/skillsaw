The official MCP Registry verifies npm package ownership with the `mcpName`
field in `package.json`. It must exactly match the server `name` in
`server.json`, as documented in the Registry's
[npm package requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx#npm-packages).

## What is checked

For each npm package with an exact version, the rule selects a local
`package.json` only when path or repository metadata links it to `server.json`.
It checks the nearest package boundary, an exact `repository.subfolder`, or one
uniquely corroborated `repository.url` and `repository.directory` match.
Ambiguous and external packages stay quiet; missing npm versions are reported
by `mcp-registry-server-json-valid`.

For the selected package, the rule verifies that:

- `package.json` declares a string-valued `mcpName`; and
- `mcpName` matches the exact `server.json` `name`, including case.

This check is entirely offline and never downloads npm metadata.

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
