# SkillSaw TODO — Content & Autofixing Polish

Please work on the list below.  As you complete items, check them off.  You can use subagents with worktrees if you prefer, but all needs to merged to the pr/foundation-content-llm branch.  Monitor the pull request's github verifications and fix any failures. Use the skillsaw-panel-review at the end using a subagent with opus asking, asking it to pay close attention to details, and address any feedback to achieve an approval. You can only push to the not-stbenjam fork.


 - [x] Update apm.yml to target claude, cursor, gemini, and opencode
 - [x] Move README contributing section to a new CONTRIBUTING.md doc
 - [x] Please provide a DEVELOPMENT.md with instructions about how to develop on skillsaw
 - [x] Ensure requirement-dev.txt is up to date
 - [x] Provide makefile targets to help with development more (existing ones are sufficient)
 - [x] Don't hardcode numbers in the README, just say "More than a dozen rules that analyze...." 
 
## How to run LLM tests

VERTEXAI_LOCATION=global SKILLSAW_MODEL="vertex_ai/claude-sonnet-4-6" SKILLSAW_LLM_INTEGRATION=1 .venv/bin/pytest tests/test_llm_integration.py -v -k "Live"
gg
