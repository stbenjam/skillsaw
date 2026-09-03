# Independent verification & critique

Launch an independent subagent after `CHECKLIST.md` is compiled to review reports, previous fixes, development guidelines, and recent session decisions. The goal is to provide a fresh, objective check on all proposed changes.

**Verification tasks:**

1. **Reproduce issues**: Test each Tier 1 item against sample fixtures or corpus repositories to ensure the problem is genuine and accurately diagnosed.
2. **Review proposed fixes**: Ensure solutions resolve the root issue without introducing new false negatives, conflicting with established design patterns, or adding unnecessary complexity.
3. **Verify prioritization**: Check that fixes are ranked by real-world impact and clarity, keeping high-confidence fixes at the top.
4. **Check for gaps**: Review recent commits and top-volume findings across corpus repositories to make sure no important regressions were overlooked.
5. **Release readiness check**: Confirm all user-facing changes and configuration updates are ready to be documented in the release notes.

**Output**: Reject an item that does not reproduce, and demote one whose fix would regress or add complexity, before writing the list. Then provide an approved Tier 1 list of up to 10 prioritized fixes with recommended solutions and test cases, along with an ordered list for subsequent batches.
