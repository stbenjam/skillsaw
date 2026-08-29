MCP Registry publishers describe a server in `server.json`. This rule
validates that document against the official
[2025-12-11 schema](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json)
and the Registry's semantic publishing constraints.

## What is checked

- The file is strict JSON containing an object.
- `$schema` is the canonical 2025-12-11 schema identifier.
- Required fields and nested objects conform to the bundled released schema,
  including URI, length, hash, argument, and transport shapes.
- `name` contains exactly one slash. Its namespace is a true reverse-DNS
  sequence of valid labels, and its server portion starts and ends with an
  ASCII letter or digit.
- Top-level and package versions identify one exact release rather than
  `latest`, a comparator, a wildcard, an OR expression, or a hyphen range.
  Package checks also recognize registry-native requirement syntax such as
  PyPI specifier lists, Cargo comma-joined requirements, and NuGet intervals.
- npm package versions use strict SemVer; other package registries may use
  their own format-specific exact-version syntax.
- Package transports are `stdio`, `streamable-http`, or `sse`. Remote
  transports are `streamable-http` or `sse`.
- MCPB packages declare the required `fileSha256` integrity hash.
- Icon sources use HTTPS, and `repository.subfolder` is a clean relative path
  without empty, current-directory, or parent-directory segments.
- `registryType` is one of `npm`, `pypi`, `cargo`, `oci`, `nuget`, or
  `mcpb` by default. These are the package types documented by the
  [official Registry](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx).

The schema is bundled from a pinned revision of the official static-assets
repository. Validation is fully offline and never follows a repository-owned
schema URL.

## Configuration

Self-hosted registries can replace the accepted package vocabulary:

```yaml
rules:
  mcp-registry-server-json-valid:
    registry-types:
      - npm
      - company-internal
```

Transport values remain fixed because they select protocol-defined execution
models rather than a registry backend.

## Detection and explicit linting

Automatic detection requires a canonical MCP Registry schema URL or the
Registry's distinctive identity and package/remote shape. An unrelated
`server.json` is ignored. Use `--type mcp-registry` to validate malformed
publisher metadata that cannot identify itself.

## How to fix

Start with the current schema identifier and a reverse-DNS name:

```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.example/weather",
  "description": "Weather observations and forecasts.",
  "version": "1.0.0",
  "packages": [
    {
      "registryType": "npm",
      "identifier": "@example/weather-mcp",
      "version": "1.0.0",
      "transport": {
        "type": "stdio"
      }
    }
  ]
}
```

Run the official `mcp-publisher validate` command as a final pre-publish check;
it can also apply Registry policies that require live service or ownership
information.
