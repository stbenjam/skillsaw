# Run final verification

Run `<new-prefix>` from the repository root and confirm that it exits
successfully; bare `skillsaw` may be absent or still the old release when the
retained prefix is `uvx` or a container. A non-zero exit caused only by
findings the user declined to fix, baseline or configure is reported as such.
Any other failure (a finding from an existing rule that the new-rules scan did
not show, an `invalid-config` finding, a crash) is a defect this run
introduced: fix it before summarizing, and never file it under declined
findings. When the versions step paused the update, say so and that no pin or
rule change was made. Summarize:

- verification: the linter run with `<new-prefix>` from the repository root
  passed, or the findings the user declined that remain;
- installed and latest versions;
- added rules, with each rule's finding count in this repository;
- removed rules and any baseline cleanup applied;
- pins updated (workflows, action inputs, Makefile, pre-commit config,
  container tags in Dockerfiles or GitLab CI, PyPI pins);
- triage outcomes: fixed, baselined, and configured counts;
- every file created or modified.

Remind the user to commit every applicable artifact, including
`.skillsaw.yaml`, `.skillsaw-baseline.json`, workflow files,
`.pre-commit-config.yaml`, Makefile changes, and edited context files.
