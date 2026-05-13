---
description: Command with negative-only instructions
---

## Name
content-test:negative

## Synopsis
```text
/content-test:negative
```

## Description
Testing negative-only rule detection.

## Implementation
1. Open the configuration file
2. Parse the YAML content
3. Validate the schema
4. Check required fields exist
5. Report any missing fields
<!-- skillsaw-assert content-negative-only -->
6. Never use eval in production code.
7. Print the validation results
