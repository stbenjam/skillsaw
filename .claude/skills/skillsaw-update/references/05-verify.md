# Run final verification

Re-run the linter with `<new-prefix>`. If it exits non-zero only on findings
the user declined to fix, baseline or configure, report them and stop; retry
only after an accepted remediation. Then run `<new-prefix>` from the
repository root and confirm that it exits successfully; bare `skillsaw` may be absent or still the old release when the
retained prefix is `uvx` or a container. Summarize:

- verification checks completed (targeted re-lint and root lint both passing);
- installed and latest versions;
- added rules, with each rule's finding count in this repository;
- removed rules and any baseline cleanup applied;
- pins updated (workflows, Makefile, pre-commit config, container tags, Dockerfiles);
- triage outcomes: fixed, baselined, and configured counts;
- every file created or modified.

Remind the user to commit every applicable artifact, including
`.skillsaw.yaml`, `.skillsaw-baseline.json`, workflow files,
`.pre-commit-config.yaml`, Makefile changes, and edited context files.
