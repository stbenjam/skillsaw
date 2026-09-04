# Run final verification

Run `<new-prefix> lint` from the repository root; bare `skillsaw` may be
absent or still the old release when the retained prefix is `uvx` or a
container. Exit 0 is a pass. A non-zero exit caused only by findings the user
declined to fix, baseline or configure is reported as such. When the new-rules
scan ran, compare against it: a finding it did not show, an `invalid-config`
finding, or a crash is a defect this run introduced, so fix it before
summarizing and never file it under declined findings. When no scan ran, or
the versions step paused the update, report remaining findings as
pre-existing and do not fix them unasked; on the paused path also say that no
pin or rule change was made. Summarize:

- verification: clean, or the declined findings that remain;
- installed and latest versions;
- added rules, with each rule's finding count in this repository;
- removed rules and any baseline cleanup applied;
- pins updated (workflows, action inputs, Makefile, pre-commit config,
  container tags in Dockerfiles or GitLab CI, PyPI pins) and `.skillsaw.yaml`'s
  `version:`;
- triage outcomes: fixed, baselined, and configured counts;
- every file created or modified.

Remind the user to commit every applicable artifact, including
`.skillsaw.yaml`, `.skillsaw-baseline.json`, workflow files,
`.pre-commit-config.yaml`, Makefile changes, and edited context files.
