# SkillSaw TODO — Content & Autofixing Polish

Please work on the list below.  As you complete items, check them off.  You can use subagents with worktrees if you prefer, but all needs to merged to the pr/foundation-content-llm branch.  Monitor the pull request's github verifications and fix any failures. Use the skillsaw-panel-review at the end, and address any feedback to achieve an approval. You can only push to the not-stbenjam fork.

## LLM Fix Pipeline

- [ ] LintTool runs full-repo linting to check a single file — scope to just the target file's failed rules (big perf win, especially with parallelism)
- [ ] No `--dry-run` mode to preview what the LLM would fix without writing
- [ ] Rollback is all-or-nothing — if total violations don't improve, everything reverts even if some files were fixed successfully. Just report what failed and let the user have the fixes we made

## Content Rules Coverage

- [ ] Rules only check top-level instruction files — skills, commands, agents, and rules markdown are blind spots (plan exists for `gather_all_content_files()`)
- [ ] No rule for detecting stale/outdated references (e.g., mentioning deprecated APIs, old model names)
- [ ] No rule for inconsistent terminology across files (calling the same thing different names)
- [ ] `content-contradiction` is pattern-based — could miss semantic contradictions that only an LLM would catch
- [ ] Review all the content-* rules for value, accuracy, and whether they are helpful or not, consider whether any new rules need to be added and if so, add them, but add rules sparingly

## Autofix Coverage

- [ ] Only content rules have `llm_fix_prompt` — structural rules (frontmatter, naming, JSON validity) could benefit from deterministic autofixes (`supports_autofix` / `fix()`)
- [ ] No way to see which rules support which fix type (`--fix` vs `--fix --llm`) from `list-rules`

## CLI Polish

- [ ] Progress bar doesn't show elapsed time or ETA
- [ ] No `--fix --llm` in the `lint` subcommand — you have to use the separate `fix` subcommand, it probably belongs in the lint subcommand, no?

## Testing

- [ ] No integration test for the LLM fix pipeline - make integration tests for every LLM fixable case, and create a .github action to test it, with openrouter (minimax 2.7 probably as default), I'll setup the keys later for you, but create the tests now.
- [ ] No test for parallel execution / thread safety

## Documentation

- [ ] Rules list needs to indicate which are auto-fixable, and what is not, and how (e.g. auto, llm, or not fixable)
- [ ] Documentation needs to be updated to highlight the context efficiency features!

