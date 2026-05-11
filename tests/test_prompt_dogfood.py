"""Dogfood test: run content-quality rules against our own LLM fix prompts."""

from pathlib import Path

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import LintTarget
from skillsaw.rules.builtin import BUILTIN_RULES
from skillsaw.rules.builtin.content_analysis import ExtraBlock
from skillsaw.rules.builtin.content_rules import (
    ContentWeakLanguageRule,
    ContentTautologicalRule,
    ContentNegativeOnlyRule,
    ContentEmbeddedSecretsRule,
    ContentBannedReferencesRule,
)

CONTENT_RULES = [
    ContentWeakLanguageRule,
    ContentTautologicalRule,
    ContentNegativeOnlyRule,
    ContentEmbeddedSecretsRule,
    ContentBannedReferencesRule,
]

SKIP_SELF = {
    "content-weak-language": {"content-weak-language"},
    "content-tautological": {"content-tautological"},
    "content-contradiction": {"content-tautological"},
}


def _make_context(prompt_text: str) -> RepositoryContext:
    """Build a minimal RepositoryContext with a single ExtraBlock containing the prompt."""
    fake_root = Path("/fake")
    block = ExtraBlock(path=fake_root / "prompt.md", body=prompt_text)
    root = LintTarget(path=fake_root, children=[block])
    root.set_parents()
    ctx = RepositoryContext.__new__(RepositoryContext)
    ctx._root_path = fake_root
    ctx._lint_tree = root
    return ctx


def _rules_with_prompts():
    for rule_cls in BUILTIN_RULES:
        rule = rule_cls()
        prompt = rule.llm_fix_prompt
        if prompt:
            yield rule.rule_id, prompt


@pytest.mark.parametrize(
    "rule_id,prompt",
    list(_rules_with_prompts()),
    ids=[rid for rid, _ in _rules_with_prompts()],
)
def test_prompt_passes_content_rules(rule_id, prompt):
    context = _make_context(prompt)
    skip = SKIP_SELF.get(rule_id, set())

    all_violations = []
    for content_rule_cls in CONTENT_RULES:
        content_rule = content_rule_cls()
        if content_rule.rule_id in skip:
            continue
        violations = content_rule.check(context)
        all_violations.extend(violations)

    if all_violations:
        report = "\n".join(f"  [{v.rule_id}] {v.message}" for v in all_violations)
        pytest.fail(f"Prompt for rule '{rule_id}' has content violations:\n{report}")
