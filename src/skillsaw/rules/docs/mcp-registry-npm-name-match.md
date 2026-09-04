The official MCP Registry verifies npm package ownership with the `mcpName`
field in `package.json`. It must exactly match the server `name` in
`server.json`, as documented in the Registry's
[npm package requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx#npm-packages).

## What is checked

For each npm package with an exact version, the rule selects a local
`package.json` from deterministic evidence: the nearest package boundary or one
corroborated package `repository.url` and `repository.directory` match. With no
conflicting package boundary, one unique local package with the exact published
name, version, and repository is also checked. A private root package may act as
a workspace container, while a declared package directory must match the
package's path. The server's `repository.subfolder` describes source location,
not package location. Ambiguous and external packages stay quiet; missing npm
versions are reported by
`mcp-registry-server-json-valid`.

When a workspace container shares the published name and version with a member,
the rule checks the declared member. Literal paths and positive `*`, `?` and
whole-segment `**` workspace patterns are supported, including a leading `./`.
The list and `{ "packages": [...] }` declaration forms are both recognized.
Complex patterns, including braces, character classes and ordered exclusions,
leave workspace membership unresolved. The rule then stays quiet unless other
repository-directory evidence identifies the package; it does not assume the
container is published because it could not resolve those patterns.

For the selected package, the rule verifies that:

- `package.json` declares a string-valued `mcpName`; and
- `mcpName` matches the exact `server.json` `name`, including case.

This check is entirely offline and never downloads npm metadata.
Exact publish-time placeholders are skipped until the server and package
coordinates have been rendered.

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
