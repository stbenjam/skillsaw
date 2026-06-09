# Threat Model: skillsaw

## 1. System context

skillsaw is a CLI linter and autofixer for agentic contextual building
blocks — CLAUDE.md files, plugin manifests, skill definitions, hooks,
MCP configs, and similar artifacts that instruct AI coding assistants.
It is distributed as a Python package on PyPI and runs as a local
developer tool or in CI pipelines (GitHub Actions). It has no network
listeners and no daemon mode.

skillsaw reads files from a target repository, parses them (Markdown,
YAML, JSON), evaluates them against ~40 built-in lint rules, and reports
violations. It can also automatically fix violations via deterministic
rewrites or by delegating to an external LLM (Claude, GPT, etc.) through
litellm. A GitHub Action mode posts lint results as PR review comments.

**Key assumptions:**

- The operator who invokes `skillsaw` controls the target repository.
  In CI, the repository content comes from a pull request and is
  potentially adversary-controlled.
- Config files (`.skillsaw.yaml`) and custom rule files
  (`.skillsaw-custom.py`) are inside the repository and therefore share
  the trust level of the repository content.
- The LLM provider (when `--llm` is used) is a remote API. skillsaw
  sends file contents to it and applies returned edits to disk.
- Dependencies (PyYAML, ruamel.yaml, litellm) are sourced from PyPI.
  We delegate YAML parsing correctness to those libraries.

## 2. Assets

| asset | description | sensitivity |
|---|---|---|
| developer_workstation | Local filesystem of the operator running skillsaw | critical |
| repository_files | Files in the target repo that skillsaw reads and may modify | high |
| ci_gate_integrity | Correctness of the pass/fail exit code in CI pipelines | high |
| llm_api_credentials | API keys for LLM providers (env vars, litellm config) | critical |
| pypi_package | The published skillsaw package on PyPI | critical |
| github_token | `GITHUB_TOKEN` used by the review Action to post PR comments | high |

## 3. Entry points & trust boundaries

| entry_point | description | trust_boundary | reachable_assets |
|---|---|---|---|
| target_repo_files | Markdown, YAML, JSON files in the linted repository | untrusted repo content → parser/rule engine | repository_files, ci_gate_integrity |
| skillsaw_yaml_config | `.skillsaw.yaml` configuration loaded from the target repo | untrusted repo content → config loader (yaml.safe_load) | ci_gate_integrity, repository_files |
| custom_rule_files | Python files loaded via `custom-rules` config directive | untrusted repo content → Python exec_module (arbitrary code execution by design) | developer_workstation, repository_files, llm_api_credentials |
| cli_arguments | Command-line arguments (--path, --config, --patch-file, --model) | local user → CLI parser | repository_files, developer_workstation |
| llm_api_responses | Tool-call responses from the LLM during `fix --llm` | remote LLM API → tool dispatch → file writes | repository_files |
| patch_file | Saved `.skillsaw-llm-patch.diff` applied via `git apply` | untrusted file → subprocess shell-out | repository_files |
| pypi_supply_chain | Package installation from PyPI | PyPI → developer workstation | developer_workstation, pypi_package |
| github_action_env | Environment variables and PR context in CI | CI environment → review.py → GitHub API | github_token, ci_gate_integrity |
| marketplace_json_sources | Plugin source paths declared in marketplace.json | untrusted repo content → path resolution | repository_files |

## 4. Threats

| id | threat | actor | surface | asset | impact | likelihood | status | controls | evidence |
|---|---|---|---|---|---|---|---|---|---|
| T1 | Arbitrary code execution via custom rules: a malicious `.skillsaw.yaml` points `custom-rules` at a Python file containing attacker code, which is loaded with `exec_module` | remote_unauth | custom_rule_files | developer_workstation | critical | possible | mitigated | `--no-custom-rules` flag skips loading custom rules entirely. Recommended for CI on untrusted PRs. Custom rules remain an intentional feature for trusted contexts; the file must exist in the repo. No sandbox. | `--no-custom-rules` (v0.12.0) |
| T2 | LLM-driven file write outside repo root: the LLM issues a `write_file` or `replace_section` tool call with a path that escapes the repo via `../` traversal | remote_unauth | llm_api_responses | developer_workstation | critical | very_rare | mitigated | `_resolve_safe()` in `llm/tools.py` checks `is_relative_to(root)` before every read/write | None |
| T3 | Prompt injection via linted file content: adversarial text in a CLAUDE.md or SKILL.md file manipulates the LLM during `fix --llm` to write malicious content or exfiltrate data through tool calls | remote_unauth | target_repo_files, llm_api_responses | repository_files, llm_api_credentials | high | possible | partially_mitigated | LLM is scoped to read/write/replace/lint/diff tools only; rollback reverts changes that don't reduce violations; no network-access tools. Credentials in env vars are not directly exposed to the LLM but may appear in file content if present in the repo. | None — general class risk for LLM-in-the-loop tools |
| T4 | CI gate bypass via crafted file content: a PR author crafts files that cause skillsaw to exit 0 despite containing violations (e.g., triggering an unhandled exception that is silently caught, or exploiting baseline/suppression logic) | remote_unauth | target_repo_files, skillsaw_yaml_config | ci_gate_integrity | high | rare | partially_mitigated | Rule exceptions are caught per-rule and logged but do not abort; if all rules crash, exit 0 (no violations found). Inline suppression (`skillsaw-disable`) and baseline files can silence violations by design. | None |
| T5 | YAML deserialization issues in config or rule parsing: malformed YAML triggers unexpected behavior in PyYAML or ruamel.yaml parsers | remote_unauth | skillsaw_yaml_config, target_repo_files | developer_workstation | medium | very_rare | mitigated | Config uses `yaml.safe_load` (no arbitrary object instantiation). ruamel.yaml `YAML(typ='safe')` or round-trip mode is used for rule files. | CVE-2017-18342 (PyYAML `yaml.load` — skillsaw uses `safe_load`) |
| T6 | Path traversal via marketplace.json plugin sources: a `source` field like `"../../etc"` causes skillsaw to read/lint files outside the repo | remote_unauth | marketplace_json_sources | repository_files | medium | very_rare | mitigated | `_resolve_plugin_source()` in `context.py` calls `candidate.relative_to(self.root_path)` and rejects paths that escape the root | None |
| T7 | Patch file injection: `--apply-patch` reads a `.diff` file and passes it to `git apply`. A crafted patch could write to unexpected paths within the repo | local_user | patch_file | repository_files | medium | rare | partially_mitigated | `git apply` has its own path safety checks and operates within the working tree. However, the patch file path is user-controllable and the content is not validated beyond what `git apply --check` enforces. | None |
| T8 | Supply chain compromise of the skillsaw PyPI package or its dependencies | supply_chain | pypi_supply_chain | developer_workstation, pypi_package | critical | rare | partially_mitigated | PyPI publish uses trusted publishing (OIDC, `pypa/gh-action-pypi-publish`). No artifact signing or SBOM. Dependencies (PyYAML, ruamel.yaml, litellm) are not pinned to hashes. | None |
| T9 | GitHub token exposure or misuse in the review Action: the `GITHUB_TOKEN` is used to post comments; a compromised or confused CI environment could leak or misuse it | remote_unauth | github_action_env | github_token | high | rare | partially_mitigated | Token is scoped by GitHub Actions permissions. `review.py` uses it only for comment API calls. Token value is never logged. | None |
| T10 | LLM fix introduces vulnerable or malicious code into agent instruction files: even without prompt injection, the LLM may produce fixes that subtly weaken security controls in CLAUDE.md files | remote_unauth | llm_api_responses | repository_files | high | possible | partially_mitigated | Rollback mechanism reverts changes that don't reduce violations. `--dry-run` mode available. No human review is enforced before write. Interactive mode prompts for confirmation by default. | None |
| T11 | Denial of service via resource exhaustion: a repository with deeply nested directories, extremely large files, or circular symlinks causes excessive CPU/memory consumption during file discovery or parsing | remote_unauth | target_repo_files | developer_workstation | low | possible | partially_mitigated | `_WALK_SKIP_DIRS` skips known heavy directories (.git, node_modules, .venv). No explicit file-size limits or symlink-loop detection. `Path.resolve()` follows symlinks. | None |
| T12 | Suppression/baseline abuse to hide violations in CI: a PR adds `skillsaw-disable` comments or modifies `.skillsaw-baseline.json` to silence real violations while appearing clean | remote_unauth | target_repo_files | ci_gate_integrity | medium | likely | risk_accepted | Suppression and baseline are intentional features for adopting skillsaw incrementally. Stale baseline entries are reported. PR review should catch added suppressions. | None — design-level tradeoff |

## 5. Deprioritized

| threat | reason |
|---|---|
| Malicious operator running skillsaw with `--path /` to read arbitrary files | The operator already has filesystem access; skillsaw does not escalate privilege. Actor is `local_admin`, which is outside the threat model for a CLI tool that runs as the invoking user. |
| Bugs in Python's `argparse` or `pathlib` standard library | Upstream responsibility; filed against CPython. |
| LLM provider-side data retention or leakage of file content sent during `fix --llm` | Governed by the operator's agreement with their LLM provider (Anthropic, OpenAI, etc.). skillsaw documents that file content is sent externally. |
| Side-channel timing attacks on YAML parsing | No security-sensitive branching depends on YAML parse timing. |
| Memory-safety bugs in CPython or PyYAML C extensions | Upstream responsibility; skillsaw does not use `ctypes` or native extensions directly. |

## 6. Open questions

- ~~Should custom rule loading (`exec_module`) be gated behind an explicit opt-in flag or environment variable, rather than silently executing any Python file referenced in config? This is the highest-impact entry point.~~ Addressed: `--no-custom-rules` flag added in v0.12.0.
- Should `fix --llm` enforce a mandatory `--dry-run` first pass in CI, or should that be left to the operator's CI config?
- Should file-size limits be enforced during discovery to prevent resource exhaustion from multi-GB files in adversarial repos?
- Does the rollback mechanism in `llm_fix` reliably prevent net-negative changes, or can an adversarial prompt produce changes that pass re-lint but introduce semantic harm?
- Should the review Action validate that `GITHUB_TOKEN` has minimal required scopes before proceeding?
- Should `.skillsaw-baseline.json` modifications require a separate approval step in CI (e.g., CODEOWNERS)?

## 7. Provenance

- mode: bootstrap
- date: 2026-05-29
- target: stbenjam/skillsaw @ f22f0b5
- inputs: source code review of src/skillsaw/ (context.py, config.py, linter.py, llm/tools.py, llm/engine.py, __main__.py, action/review.py), pyproject.toml, .github/workflows/release.yml
- owner: unset

## 8. Recommended mitigations

| mitigation | threat_ids | closes_class | effort |
|---|---|---|---|
| ~~Add a `--no-custom-rules` flag and default to rejecting custom rules in CI unless explicitly opted in~~ Done: `--no-custom-rules` added in v0.12.0 | T1 | partial | S |
| Add file-size caps and symlink-loop detection to the file discovery walker | T11 | yes | S |
| Enforce `--dry-run` as default for `fix --llm` and require explicit `--write` to persist changes | T3, T10 | partial | S |
| Pin dependency hashes in `pyproject.toml` or use a lockfile, and publish an SBOM with releases | T8 | partial | M |
| Add a `--strict-baseline` CI mode that fails if `.skillsaw-baseline.json` has new entries compared to the base branch | T12 | partial | M |
| Validate patch file content (e.g., reject patches that touch files outside the repo or modify binary files) before passing to `git apply` | T7 | yes | S |
| Instrument the LLM tool-call loop with a content-safety check that flags suspicious patterns (e.g., new `exec`, `eval`, credential references) in LLM-written output before committing | T3, T10 | partial | L |
| Sign PyPI releases with Sigstore and publish provenance attestations | T8 | partial | M |
