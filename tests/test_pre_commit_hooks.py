"""Tests for the .pre-commit-hooks.yaml manifest.

Validates the hook definition offline: structure, consistency with the
console scripts declared in pyproject.toml, and the trigger regex. Running
pre-commit itself requires network access (it builds an isolated venv), so
end-to-end verification is done with `pre-commit try-repo .` manually or in CI.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
MANIFEST = REPO_ROOT / ".pre-commit-hooks.yaml"


@pytest.fixture(scope="module")
def hooks():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def skillsaw_hook(hooks):
    by_id = {h["id"]: h for h in hooks}
    return by_id["skillsaw"]


def test_manifest_is_a_list_of_hooks(hooks):
    assert isinstance(hooks, list)
    assert len(hooks) >= 1
    for hook in hooks:
        for required in ("id", "name", "entry", "language"):
            assert required in hook, f"hook {hook.get('id')} missing {required!r}"


def test_skillsaw_hook_contract(skillsaw_hook):
    assert skillsaw_hook["language"] == "python"
    # Repo-level linter: must not receive staged filenames as arguments
    assert skillsaw_hook["pass_filenames"] is False
    # The entry must invoke a console script declared in pyproject.toml
    entry_cmd = skillsaw_hook["entry"].split()[0]
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(
        rf"^{re.escape(entry_cmd)}\s*=", pyproject, re.MULTILINE
    ), f"entry {entry_cmd!r} is not a [project.scripts] console script"


def test_files_regex_compiles(skillsaw_hook):
    re.compile(skillsaw_hook["files"])


@pytest.mark.parametrize(
    "path",
    [
        "CLAUDE.md",
        "docs/CLAUDE.md",
        "AGENTS.md",
        "GEMINI.md",
        "SKILL.md",
        "skills/deploy-service/SKILL.md",
        "coding.instructions.md",
        ".github/instructions/api.instructions.md",
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        "plugins/my-plugin/.claude-plugin/plugin.json",
        ".claude/commands/deploy.md",
        ".claude/rules/python.md",
        "plugins/my-plugin/commands/hello.md",
        "commands/hello.md",
        "agents/helper.md",
        "hooks/hooks.json",
        "plugins/my-plugin/hooks/hooks.json",
        ".mcp.json",
        ".claude/settings.json",
        ".cursor/rules/style.mdc",
        ".cursorrules",
        ".github/copilot-instructions.md",
        ".kiro/steering/product.md",
        ".apm/instructions/dev.md",
        "apm.yml",
        ".skillsaw.yaml",
        ".skillsaw.yml",
        ".claudelint.yaml",
        ".skillsaw-baseline.json",
        ".coderabbit.yaml",
        "promptfooconfig.yaml",
        "evals/promptfooconfig.smoke.yml",
        "evals/regression.yaml",
    ],
)
def test_files_regex_matches_lintable_paths(skillsaw_hook, path):
    pattern = re.compile(skillsaw_hook["files"])
    assert pattern.match(path), f"expected hook to trigger on {path!r}"


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "src/skillsaw/linter.py",
        "pyproject.toml",
        "docs/architecture.md",
        "Makefile",
        "tests/test_linter.py",
        "package.json",
        ".github/workflows/ci.yml",
    ],
)
def test_files_regex_ignores_unrelated_paths(skillsaw_hook, path):
    pattern = re.compile(skillsaw_hook["files"])
    assert not pattern.match(path), f"hook should not trigger on {path!r}"
