---
name: claude-should-use-whenever
description: Formats and validates Terraform modules. Claude should use this skill whenever editing .tf files or reviewing an infrastructure change.
---

# Terraform hygiene

Run `terraform fmt` and `terraform validate` on every module the change touches, and read the plan before proposing an apply.
