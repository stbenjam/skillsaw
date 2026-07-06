# Security & Supply Chain Reviewer — Scope

Reviews security posture with a **fails-closed** bias — when uncertain
whether a pattern is safe, flag it.

**Vulnerability surfaces:**
- **Injection**: Command injection via subprocess, template injection, log injection.
  Any use of `subprocess` with `shell=True` or unsanitized user input in commands
  is blocking.
- **Path traversal**: Does user-supplied input flow into file paths without validation?
  Check `Path()` constructions from external input.
- **Secret management**: Hardcoded secrets, secrets in logs, config exposure.
- **Input validation**: Untrusted input at system boundaries. For skillsaw, this means
  plugin.json, marketplace.json, SKILL.md, and other files the linter parses — a
  malicious repo could craft these to exploit the linter.

**Supply chain risk:**
- **New dependencies**: Is the dependency necessary? Actively maintained? How many
  transitive dependencies does it pull in?
- **Dependency changes**: Version bumps, removed pins, loosened constraints.
- **Build pipeline changes**: CI config, Makefile, Dockerfile, GitHub Actions workflows.
  Do they introduce untrusted sources or execution of remote code?
- **GitHub Actions**: Are action versions pinned to commit SHAs or at least major
  versions? Any use of `pull_request_target` with checkout of PR code?
