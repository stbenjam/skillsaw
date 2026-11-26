---
name: api-contract
description: Compares API serializer changes with the published OpenAPI schema. Use when editing serializers in packages/api.
---

# API contract check

Regenerate the schema with `make schema` and diff it against
`packages/api/schema/openapi.yaml`. Any removed field is a breaking change.
