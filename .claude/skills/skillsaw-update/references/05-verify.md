# Run final verification

Run `<new-prefix> lint` from the repository root; bare `skillsaw` may be
absent or still the old release when the retained prefix is `uvx` or a
container. Exit 0 is a pass. A non-zero exit caused only by findings the user
declined to fix, baseline or configure is reported as such. A finding the
new-rules scan already showed existed before this run: report it and ask
before touching it. Anything else (a finding from an existing rule that scan
did not show, an `invalid-config` finding, a crash) is a defect this run
introduced: fix it before summarizing, and never file it under declined
findings. When the versions step paused the update, say so and that no pin or
rule change was made. Summarize:

- verification: `<new-prefix> lint` from the repository root passed, or the
  findings the user declined that remain;
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
