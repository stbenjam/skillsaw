# Fix remaining violations

Handle each remaining violation directly:

1. Read the affected file and surrounding context.
2. Run `skillsaw explain <rule-id>` before deciding the fix.
3. Make a targeted edit that preserves surrounding meaning.
4. Lint again to verify the result.

Typical corrections replace hedging or vague references with direct,
specific instructions; remove empty truisms; add required descriptions or
fields; and repair structural names or missing files. Do not rewrite whole
files to clear localized findings.

Report how many violations you fixed manually. List any finding that needs a
user decision and explain what must change, then return to the router.
