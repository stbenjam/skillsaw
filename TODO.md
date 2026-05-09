# SkillSaw TODO — Content & Autofixing Polish

Please work on the list below.  As you complete items, check them off.  You can use subagents with worktrees if you prefer, but all needs to merged to the pr/foundation-content-llm branch.  Monitor the pull request's github verifications and fix any failures. Use the skillsaw-panel-review at the end using a subagent with opus asking, asking it to pay close attention to details, and address any feedback to achieve an approval. You can only push to the not-stbenjam fork.


 - [x] Update apm.yml to target claude, cursor, gemini, and opencode
 - [x] Move README contributing section to a new CONTRIBUTING.md doc
 - [x] Provide DEVELOPMENT.md with dev instructions (review panel, make venv, LLM testing)
 - [x] Ensure requirement-dev.txt is up to date
 - [x] Provide makefile targets to help with development (existing ones are sufficient)
 - [x] Don't hardcode numbers in the README
 - [x] README features section — make concise but compelling
 - [x] Context-budget in README — full YAML, not inline JSON
 - [x] Update README promo block — content intelligence, move "formerly claudelint" below table
 - [x] Support .env for LLM integration tests (added _load_dotenv to conftest.py)
 - [x] Implement exclude config field with glob support
 - [x] Self-lint: exclude generated directories (.claude, .cursor, .gemini, .opencode, .agents)
 - [x] Add linguist-generated=true to .gitattributes for .opencode, .agents, .cursor, .gemini, .github/instructions
