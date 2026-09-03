# Run final verification

Run the linter once more with the new version and confirm it exits
successfully. Summarize:

- installed and latest versions;
- added rules, with each rule's finding count in this repository;
- removed rules and any baseline cleanup applied;
- pins updated (workflows, Makefile, pre-commit config, container tags);
- triage outcomes: fixed, baselined, and configured counts;
- every file created or modified.

Remind the user to commit every applicable artifact, including
`.skillsaw.yaml`, `.skillsaw-baseline.json`, workflow files,
`.pre-commit-config.yaml`, Makefile changes, and edited context files.
