MCP Registry publishers describe a server in `server.json`. This rule validates
the document against the released schema it declares and the Registry's
publishing constraints. Skillsaw supports every released server schema from
`2025-07-09` through `2025-12-11`.

## What is checked

- The file is strict JSON containing an object.
- `$schema` is the canonical identifier for a bundled, supported schema version.
- Required fields and nested objects conform to the bundled released schema,
  including URI, length, hash, argument, and transport shapes.
- The initial `2025-07-09` schema keeps its snake_case package fields; later
  releases use their camelCase vocabulary.
- `name` contains exactly one slash. Its namespace is a true reverse-DNS
  sequence of valid labels, and its server portion starts and ends with an
  ASCII letter or digit.
- Top-level and package versions identify one non-blank exact release rather than
  `latest`, a comparator, a wildcard, an OR expression, or a hyphen range.
  Package checks also recognize registry-native requirement syntax such as
  PyPI specifier lists, Cargo comma-joined requirements, and NuGet intervals.
- npm, PyPI, Cargo, and NuGet packages require a version. npm uses strict
  SemVer; the others use their own exact-version syntax.
- OCI packages keep their release in `identifier`. The `2025-10-11` format
  also omits MCPB `version`; `2025-10-17` and later make it optional.
- Publisher `status` and official Registry metadata are rejected after the
  releases that defined them because the Registry now manages those fields.
- Package transports are `stdio`, `streamable-http`, or `sse`. Remote
  transports are `streamable-http` or `sse`; their HTTP URL templates remain
  structurally valid after supported `{variable}` placeholders are substituted.
- MCPB packages declare the required `fileSha256` integrity hash.
- Icon sources use HTTPS, and `repository.subfolder` is a clean relative path
  without empty, current-directory, or parent-directory segments.
- `registryType` is one of `npm`, `pypi`, `cargo`, `oci`, `nuget`, or
  `mcpb` by default. These are the package types documented by the
  [official Registry](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx).

Each schema is bundled from a pinned revision of the
[official static-assets repository](https://github.com/modelcontextprotocol/static/tree/a9ba437d9fbbe92076a24b20d56449ac7c7786ac/schemas).
Validation is offline. An unknown future version receives one diagnostic and
is not interpreted using a different schema.

## Additional Registry types

Self-hosted registries can add to the package vocabulary defined by the
document's schema version:

```yaml
rules:
  mcp-registry-server-json-valid:
    registry-types:
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
