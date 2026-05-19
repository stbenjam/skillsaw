---
name: wall-of-text
description: An agent with unstructured instructions
---

This agent handles code generation tasks for the platform.
It reads the requirements from the issue tracker and creates
implementation plans based on the technical specifications.
The agent validates all inputs against the project schema
before proceeding with code generation steps.
Output files are written to the configured output directory.
All generated code must pass the linter checks before being
committed to the repository. The agent runs tests on all
generated files and reports any failures to the user.
Error messages should include the file path and line number
where the issue was detected. Recovery from errors should
be attempted three times before failing permanently.
Generated code follows the project style guide exactly.
Dependencies are resolved from the lock file automatically.
The agent tracks progress and reports completion percentage.
