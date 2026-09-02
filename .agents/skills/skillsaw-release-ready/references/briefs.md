# Briefs for reviewers and auditors

Prepare shared brief files in `~/tmp/skillsaw-audit/briefs/` so subagents share common instructions. Specific prompts only need to provide the target rule or architectural dimension, relevant files, and test criteria.

## Rule reviewers

Launch one subagent per new rule. Reviewers operate read-only on the repository and keep scratch files under `~/tmp/skillsaw-audit/work/<rule-id>/`.

**Review checklist:**
1. **Conventions**: Review the rule implementation, documentation, tests, and project development guidelines.
2. **Upstream accuracy**: Compare checks against upstream schemas, official tools, or CLIs to ensure valid configurations aren't mistakenly flagged.
3. **Corpus testing**: Run the rule on real-world repositories. Note any false positives with `file:line` references and explanations.
4. **Edge cases**: Test unusual but valid structures (lists vs. scalars, optional fields, nested folders, Unicode, empty files). Verify that invalid input yields clear findings rather than crashes, and confirm autofix idempotency.
5. **File discovery**: Confirm that discovery finds intended files while ignoring build artifacts or vendor folders (like `node_modules`).
6. **Documentation & messages**: Ensure diagnostic messages and documentation accurately describe what the rule checks and how to resolve violations.
7. **Performance**: Check execution time on large repositories.
8. **Consistency**: Look for opportunities to share helpers and match conventions of neighboring rules.

**Output**: Save report to `reports/rule-<id>.md` with a clear status (SHIP, SHIP-WITH-FIXES, or HOLD), sample findings (P0–P3), recommended improvements, and a concise summary.

## Dimension auditors

Launch one subagent per architectural dimension. Save findings to `reports/audit-<dimension>.md` with an overall health rating (1–5) and key takeaways:

- **Core architecture**: Layering boundaries, tree construction stages, caching/memoization, and Python compatibility.
- **Rules layer**: Helper consistency across ecosystems, naming conventions, configuration schemas, and doc accuracy.
- **CLI & UX**: Subcommands, flags, exit codes, and output formatting across different repo layouts.
- **Performance**: Comparative benchmarks between the last release and HEAD, profiling hotspots.
- **Modified rules**: Differential scan of updated existing rules to catch unintended regressions.
- **Real-world sweep**: Full scans across corpus repositories under default and force-enabled configs, testing `skillsaw fix` idempotency.
- **Security**: Path containment, symlink handling, safe YAML/JSON loading, regex safety, and network isolation.
- **Test quality**: Test coverage for new code paths, fixture realism, and ensuring `make update` runs cleanly.
- **Docs & release**: Alignment between CLI docs and `--help`, rule documentation, site builds, and draft release notes.
