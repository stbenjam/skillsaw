# Writing New Linter Rules

## Line Numbers

Rules MUST report line numbers in violations whenever the violation can be
traced to a specific line in a file. This enables the GitHub Action to post
inline PR comments on the exact line.

- **Frontmatter fields:** Use `_frontmatter_key_line()` (see
  `agentskills.py`) or a similar helper to find the line of the offending key.
- **Markdown sections:** Scan for the heading or content that triggered the
  violation and report its line.
- **JSON files:** Exempt from line number requirements. The `json` module does
  not preserve line numbers and scanning raw JSON text for keys is unreliable.
  File-level reporting is acceptable for JSON validation rules.
- **File-level violations** (missing file, bad directory name) naturally have no
  line number — that's fine.
- **Missing fields:** Don't fabricate a line number (e.g. hardcoding `line=1`).
  If a field is missing, there's no line to point to — omit the line number.

When in doubt, report the line. An approximate line is better than no line.
