---
description: Build a widget from the current specification
argument-hint: "[widget-name] [--watch]"
---

## Name
widget-maker:build

## Synopsis
```
/widget-maker:build my-widget --watch
```

## Description
Compiles a widget from its specification file into a deployable artifact.
Supports watch mode for iterative development.

## Implementation
1. Read the widget specification from `widget.yaml`
2. Validate all required fields are present
3. Compile templates and assets into a single bundle
4. Write output to `dist/` directory
5. If `--watch` is set, monitor source files for changes and rebuild
