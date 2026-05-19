---
name: widget-lint
description: Validate widget specification files against the ACME widget schema
---

# Widget Lint

Validates widget specification files (`widget.yaml`) against the ACME
widget schema to catch configuration errors before build time.

## When to Use

Invoke this skill when creating or modifying widget specification files
to verify they conform to the schema.

## Implementation Steps

### Step 1: Find Specifications

Locate all `widget.yaml` files in the current directory tree:
```bash
find . -name "widget.yaml" -type f
```

### Step 2: Validate Each File

For each specification file:
- Parse the YAML content
- Check required fields: `name`, `version`, `type`, `components`
- Validate `type` is one of: `dashboard`, `card`, `modal`, `sidebar`
- Verify all component references resolve to existing files

### Step 3: Report Results

List all validation errors and warnings grouped by file path.
