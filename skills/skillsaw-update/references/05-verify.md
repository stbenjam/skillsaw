# Run final verification

Re-run the linter until it exits successfully.
Then run `skillsaw` from the repository root and confirm that it exits
successfully. Summarize:

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
