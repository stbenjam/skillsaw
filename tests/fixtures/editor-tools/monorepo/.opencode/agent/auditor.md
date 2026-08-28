---
description: Audits direct dependency licences against the allowlist. Use when cutting a release or when a new dependency is added.
mode: subagent
---

Read `package.json` and `requirements.txt`, then list every direct
dependency whose licence is not in `docs/allowed-licences.md`.

<!-- skillsaw-assert content-weak-language -->
You should probably check the transitive dependencies too.

Stop after producing the list. Do not change any manifest.
