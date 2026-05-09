# Developing skillsaw

## Prerequisites

- Python 3.9+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- GNU Make

## Setup

```bash
make venv
```

This creates a `.venv/` virtualenv and installs skillsaw in editable mode with all dev dependencies (pytest, black, mypy, litellm).

## Running tests

```bash
make test         # full suite with coverage
```

Tests run against Python 3.9–3.14 in CI. Locally, your active Python version is used.

## Formatting and linting

```bash
make format       # auto-format with black
make lint         # check formatting (CI uses this)
```

Black is configured for line-length 100 in `pyproject.toml`.

## Regenerating generated files

```bash
make update       # regenerate everything: APM, example config, README docs, .claude/README.md
```

**Always run `make update` before opening a PR.** This regenerates:
- `.skillsaw.yaml.example` — example config from builtin rules
- README.md — rule documentation table and Content Intelligence section
- `.claude/README.md` — `skillsaw docs` output for Claude Code
- `.claude/`, `.cursor/`, `.gemini/`, `.opencode/` — APM-compiled instructions and skills

The `verify-update` CI check will fail if generated files are stale.

## LLM integration tests

LLM-powered autofix tests are skipped by default. Any model supported by [LiteLLM](https://docs.litellm.ai/docs/providers) works — Vertex AI is recommended.

```bash
# Vertex AI (recommended — no API key needed if authenticated via gcloud)
VERTEXAI_LOCATION=global \
SKILLSAW_MODEL="vertex_ai/claude-sonnet-4-6" \
SKILLSAW_LLM_INTEGRATION=1 \
  .venv/bin/pytest tests/test_llm_integration.py -v -k "live"

# OpenRouter
OPENROUTER_API_KEY=your-key \
SKILLSAW_MODEL="openrouter/minimax/minimax-m2.7" \
SKILLSAW_LLM_INTEGRATION=1 \
  .venv/bin/pytest tests/test_llm_integration.py -v -k "live"

# Local model via llama.cpp
SKILLSAW_MODEL="openai/gemma-4-26b-a3b" \
OPENAI_API_BASE=http://localhost:8080/v1 \
SKILLSAW_LLM_INTEGRATION=1 \
  .venv/bin/pytest tests/test_llm_integration.py -v -k "live"
```

Models we've tested successfully: Gemma 4 26B A3B (llama.cpp), MiniMax M2.7 (OpenRouter), Claude Sonnet 4.6 (Vertex AI).

The mock tests (`test_mock_fix`) always run and use a `FakeProvider` — no API key needed.

## Writing new rules

See `.claude/rules/new-linter-rules.md` for the full guide. Key points:

- Subclass `Rule` in `src/skillsaw/rules/builtin/`
- Register in `src/skillsaw/rules/builtin/__init__.py`
- Set `repo_types` to control when `enabled: auto` fires
- Set `since` to the next release version so existing configs aren't surprised
- Report line numbers in violations whenever possible
- Add tests in `tests/test_<category>.py`
- Run `make update` to regenerate docs

## Project structure

```
src/skillsaw/
├── __main__.py          # CLI entry point
├── config.py            # Config loading, rule enabling logic
├── context.py           # Repo type detection
├── linter.py            # Orchestration, LLM fix loop
├── rule.py              # Base Rule class
├── rules/builtin/       # All builtin rules
├── llm/                 # LLM autofix engine
│   ├── engine.py        # Conversation loop with tool dispatch
│   ├── tools.py         # Scoped tools (read, write, replace, lint, diff)
│   └── _litellm.py      # CompletionProvider protocol and LiteLLM wrapper
└── marketplace/         # Scaffolding CLI (skillsaw add)
```

## Review panel

The project includes a review panel skill for thorough PR review:

```
/skillsaw-review-panel pr <number>    # review a PR
/skillsaw-review-panel                # review the current local branch
```

This runs 5 specialist reviewers (architecture, Python, security, QA, docs) plus an arbiter, and posts a structured verdict as a PR comment.

## Pre-PR checklist

1. `make test` — full test suite passes
2. `make lint` — formatting is clean
3. `make update` — generated files are current
4. Bump version via `scripts/bump-version.sh` (for releases)
5. Test against `openshift-eng/ai-helpers`: clone it, run `skillsaw`, ensure exit 0
