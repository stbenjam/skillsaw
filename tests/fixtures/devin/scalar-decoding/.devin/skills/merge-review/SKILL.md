---
defaults: &defaults
  agent: []
<<: *defaults
permission-defaults: &permissions
  allow: invalid-scalar
permissions:
  <<: *permissions
  deny: [Read]
description: Inspect local metadata. Use when reviewing native configuration fields.
---
# Review explicit configuration

Inspect the fields explicitly declared by this skill and record their values.
Keep extension metadata separate from fields understood by the consumer.
