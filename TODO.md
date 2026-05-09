# SkillSaw TODO — Content & Autofixing Polish

Please work on the list below.  As you complete items, check them off.  You can use subagents with worktrees if you prefer, but all needs to merged to the pr/foundation-content-llm branch.  Monitor the pull request's github verifications and fix any failures. Use the skillsaw-panel-review at the end using a subagent with opus asking, asking it to pay close attention to details, and address any feedback to achieve an approval. You can only push to the not-stbenjam fork.

    - [x] Fix false-positive LLM tests: `content-instruction-budget` and `content-inconsistent-terminology` produce violations with `file_path=None` (cross-file rules). The `llm_fix` pipeline groups by file and silently drops these, so no LLM call is made and tests pass without actually fixing anything. Fix: emit per-file violations so `llm_fix` can process them. Also fix `LintTool` (tools.py:151) which doesn't pass `since_version` to `is_rule_enabled()`.
    - [x] agentskill-name: add autofix, use directory name
    - [x] agentskill-valid: add autofix(llm), use directory to fix name, and get llm to generate description of skill
    - [x] -naming, -names rules: possible to just downcase and convert to kebab case, unless the directory is also poorly named or something
    - [x] plugin-readme: autofix(llm): can write a README for the plugin.  Keep it brief
    - [x] marketplace-regstration: autofix: you can register the plugins in the marketplace
    - [x] context-budget: should be auto for 0.7.0+, review limits: do they match reccomendations online? can you source a study about effective sizes for each category and include those references 
    - [x] content-critical-position: elevate this to warning
    - [x] content-readme-overlap: delete this rule, i don't find it useful
    - [x] content-section-length: is length configurable? why measure by lines and not tokens (what if no newlines!)
    - [x] content-stale-references: is it configurable? e.g. could be used to ban certain models if allowed, maybe this could just be content-banned-references instead

    - [x] Update the PR description on stbenjam/skillsaw PR #59 to accurately describe all the changes in this branch
    - [x] Jazz up the README to highlight dynamic rules and LLM fixing capabilities
    - [ ] LASTLY: run all tests, including LLM tests (see below example), push to pr/foundation-content-llm branch, and make sure the PR to stbenjam/skillsaw passes all github tests.  Stop the cron job when you're done.

## How to run LLM tests

VERTEXAI_LOCATION=global SKILLSAW_MODEL="vertex_ai/claude-sonnet-4-6" SKILLSAW_LLM_INTEGRATION=1 .venv/bin/pytest tests/test_llm_integration.py -v -k "Live"

