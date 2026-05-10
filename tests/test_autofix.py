"""
Tests for the autofix framework infrastructure
"""

import json
from pathlib import Path
from typing import List

import pytest

from skillsaw.rule import (
    AutofixConfidence,
    AutofixResult,
    Rule,
    RuleViolation,
    Severity,
)
from skillsaw.context import RepositoryContext
from skillsaw.config import LinterConfig
from skillsaw.linter import Linter
from skillsaw.rules.builtin.skills import SkillFrontmatterRule
from skillsaw.rules.builtin.agents import AgentFrontmatterRule
from skillsaw.rules.builtin.command_format import CommandNamingRule


class NoFixRule(Rule):
    """Rule without autofix — backward-compat check."""

    @property
    def rule_id(self) -> str:
        return "test-no-fix"

    @property
    def description(self) -> str:
        return "Rule without autofix"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return [self.violation("something wrong")]


class SafeFixRule(Rule):
    """Rule that provides a safe autofix."""

    @property
    def rule_id(self) -> str:
        return "test-safe-fix"

    @property
    def description(self) -> str:
        return "Rule with safe autofix"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        target = context.root_path / "fixme.txt"
        if target.exists() and "BAD" in target.read_text():
            violations.append(self.violation("Contains BAD", file_path=target))
        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results = []
        for v in violations:
            if v.file_path and v.file_path.exists():
                original = v.file_path.read_text()
                fixed = original.replace("BAD", "GOOD")
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Replaced BAD with GOOD",
                        violations_fixed=[v],
                    )
                )
        return results


class SuggestFixRule(Rule):
    """Rule that provides a suggested autofix."""

    @property
    def rule_id(self) -> str:
        return "test-suggest-fix"

    @property
    def description(self) -> str:
        return "Rule with suggested autofix"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        target = context.root_path / "suggest.txt"
        if target.exists() and "MAYBE" in target.read_text():
            violations.append(self.violation("Contains MAYBE", file_path=target))
        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results = []
        for v in violations:
            if v.file_path and v.file_path.exists():
                original = v.file_path.read_text()
                fixed = original.replace("MAYBE", "YES")
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SUGGEST,
                        original_content=original,
                        fixed_content=fixed,
                        description="Replaced MAYBE with YES",
                        violations_fixed=[v],
                    )
                )
        return results


class PartialFixRule(Rule):
    """Rule that fixes some violations but not all."""

    @property
    def rule_id(self) -> str:
        return "test-partial-fix"

    @property
    def description(self) -> str:
        return "Rule with partial autofix"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return [
            self.violation("fixable issue", file_path=context.root_path / "a.txt"),
            self.violation("unfixable issue"),
        ]

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        fixable = [v for v in violations if v.file_path is not None]
        results = []
        for v in fixable:
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=v.file_path,
                    confidence=AutofixConfidence.SAFE,
                    original_content="old",
                    fixed_content="new",
                    description="Fixed a.txt",
                    violations_fixed=[v],
                )
            )
        return results


# --- Unit tests ---


class TestAutofixResult:
    def test_dataclass_fields(self):
        result = AutofixResult(
            rule_id="test",
            file_path=Path("/tmp/test.txt"),
            confidence=AutofixConfidence.SAFE,
            original_content="before",
            fixed_content="after",
            description="test fix",
        )
        assert result.rule_id == "test"
        assert result.confidence == AutofixConfidence.SAFE
        assert result.original_content == "before"
        assert result.fixed_content == "after"
        assert result.violations_fixed == []

    def test_with_violations_fixed(self):
        v = RuleViolation(rule_id="test", severity=Severity.ERROR, message="bad")
        result = AutofixResult(
            rule_id="test",
            file_path=Path("/tmp/test.txt"),
            confidence=AutofixConfidence.SUGGEST,
            original_content="a",
            fixed_content="b",
            description="fix",
            violations_fixed=[v],
        )
        assert len(result.violations_fixed) == 1


class TestAutofixConfidence:
    def test_values(self):
        assert AutofixConfidence.SAFE.value == "safe"
        assert AutofixConfidence.SUGGEST.value == "suggest"


class TestRuleSupportsAutofix:
    def test_rule_without_fix_override(self):
        rule = NoFixRule()
        assert rule.supports_autofix is False

    def test_rule_with_fix_override(self):
        rule = SafeFixRule()
        assert rule.supports_autofix is True

    def test_default_fix_returns_empty(self):
        rule = NoFixRule()
        context = None  # not needed for base impl
        assert rule.fix(context, []) == []


class TestLinterFix:
    def test_fix_with_no_violations(self, valid_plugin):
        context = RepositoryContext(valid_plugin)
        config = LinterConfig.default()
        linter = Linter(context, config)
        _violations, fixes = linter.fix()
        assert fixes == []

    def test_fix_applies_safe_fixes(self, temp_dir):
        target = temp_dir / "fixme.txt"
        target.write_text("This is BAD content")

        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        linter = Linter(context, config)
        linter.rules = [SafeFixRule()]

        violations, fixes = linter.fix()
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SAFE
        assert fixes[0].fixed_content == "This is GOOD content"
        assert len(violations) == 0

    def test_fix_returns_suggest_fixes(self, temp_dir):
        target = temp_dir / "suggest.txt"
        target.write_text("This is MAYBE content")

        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        linter = Linter(context, config)
        linter.rules = [SuggestFixRule()]

        violations, fixes = linter.fix()
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST
        assert len(violations) == 0

    def test_unfixable_violations_remain(self, temp_dir):
        (temp_dir / "a.txt").write_text("content")

        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        linter = Linter(context, config)
        linter.rules = [PartialFixRule()]

        violations, fixes = linter.fix()
        assert len(fixes) == 1
        assert len(violations) == 1
        assert violations[0].message == "unfixable issue"

    def test_rules_without_fix_pass_through(self, temp_dir):
        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        linter = Linter(context, config)
        linter.rules = [NoFixRule()]

        violations, fixes = linter.fix()
        assert len(fixes) == 0
        assert len(violations) == 1


class TestApplyFixes:
    def test_apply_safe_fixes(self, temp_dir):
        target = temp_dir / "test.txt"
        target.write_text("original")

        fix = AutofixResult(
            rule_id="test",
            file_path=target,
            confidence=AutofixConfidence.SAFE,
            original_content="original",
            fixed_content="fixed",
            description="test fix",
        )

        applied = Linter.apply_fixes([fix])
        assert len(applied) == 1
        assert target.read_text() == "fixed"

    def test_apply_skips_suggest_by_default(self, temp_dir):
        target = temp_dir / "test.txt"
        target.write_text("original")

        fix = AutofixResult(
            rule_id="test",
            file_path=target,
            confidence=AutofixConfidence.SUGGEST,
            original_content="original",
            fixed_content="fixed",
            description="test fix",
        )

        applied = Linter.apply_fixes([fix])
        assert len(applied) == 0
        assert target.read_text() == "original"

    def test_apply_suggest_when_requested(self, temp_dir):
        target = temp_dir / "test.txt"
        target.write_text("original")

        fix = AutofixResult(
            rule_id="test",
            file_path=target,
            confidence=AutofixConfidence.SUGGEST,
            original_content="original",
            fixed_content="fixed",
            description="test fix",
        )

        applied = Linter.apply_fixes([fix], confidence=AutofixConfidence.SUGGEST)
        assert len(applied) == 1
        assert target.read_text() == "fixed"

    def test_apply_mixed_confidence(self, temp_dir):
        safe_target = temp_dir / "safe.txt"
        safe_target.write_text("original-safe")

        suggest_target = temp_dir / "suggest.txt"
        suggest_target.write_text("original-suggest")

        fixes = [
            AutofixResult(
                rule_id="a",
                file_path=safe_target,
                confidence=AutofixConfidence.SAFE,
                original_content="original-safe",
                fixed_content="fixed-safe",
                description="safe fix",
            ),
            AutofixResult(
                rule_id="b",
                file_path=suggest_target,
                confidence=AutofixConfidence.SUGGEST,
                original_content="original-suggest",
                fixed_content="fixed-suggest",
                description="suggest fix",
            ),
        ]

        applied = Linter.apply_fixes(fixes)
        assert len(applied) == 1
        assert safe_target.read_text() == "fixed-safe"
        assert suggest_target.read_text() == "original-suggest"

    @pytest.mark.parametrize(
        "requested, expected_applied",
        [
            (AutofixConfidence.SAFE, 0),
            (AutofixConfidence.SUGGEST, 0),
            (AutofixConfidence.LLM, 1),
        ],
    )
    def test_apply_llm_confidence_filtering(self, temp_dir, requested, expected_applied):
        target = temp_dir / "test.txt"
        target.write_text("original")

        fix = AutofixResult(
            rule_id="test",
            file_path=target,
            confidence=AutofixConfidence.LLM,
            original_content="original",
            fixed_content="fixed",
            description="test fix",
        )

        applied = Linter.apply_fixes([fix], confidence=requested)
        assert len(applied) == expected_applied
        assert target.read_text() == ("fixed" if expected_applied else "original")

    def test_apply_llm_includes_all_confidence_levels(self, temp_dir):
        """When confidence=LLM, all fix levels (SAFE, SUGGEST, LLM) are applied."""
        safe_target = temp_dir / "safe.txt"
        safe_target.write_text("original-safe")

        suggest_target = temp_dir / "suggest.txt"
        suggest_target.write_text("original-suggest")

        llm_target = temp_dir / "llm.txt"
        llm_target.write_text("original-llm")

        fixes = [
            AutofixResult(
                rule_id="a",
                file_path=safe_target,
                confidence=AutofixConfidence.SAFE,
                original_content="original-safe",
                fixed_content="fixed-safe",
                description="safe fix",
            ),
            AutofixResult(
                rule_id="b",
                file_path=suggest_target,
                confidence=AutofixConfidence.SUGGEST,
                original_content="original-suggest",
                fixed_content="fixed-suggest",
                description="suggest fix",
            ),
            AutofixResult(
                rule_id="c",
                file_path=llm_target,
                confidence=AutofixConfidence.LLM,
                original_content="original-llm",
                fixed_content="fixed-llm",
                description="llm fix",
            ),
        ]

        applied = Linter.apply_fixes(fixes, confidence=AutofixConfidence.LLM)
        assert len(applied) == 3
        assert safe_target.read_text() == "fixed-safe"
        assert suggest_target.read_text() == "fixed-suggest"
        assert llm_target.read_text() == "fixed-llm"


class TestEndToEndFix:
    def test_full_fix_workflow(self, temp_dir):
        """Test the complete workflow: check -> fix -> apply -> verify."""
        target = temp_dir / "fixme.txt"
        target.write_text("This has BAD content")

        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        linter = Linter(context, config)
        linter.rules = [SafeFixRule()]

        violations_before = linter.run()
        assert len(violations_before) == 1

        _violations, fixes = linter.fix()
        applied = Linter.apply_fixes(fixes)

        assert len(applied) == 1
        assert target.read_text() == "This has GOOD content"

        violations_after = linter.run()
        assert len(violations_after) == 0


class TestSkillFixBothFieldsMissing:
    """Regression: when both name and description are missing from SKILL.md
    frontmatter, the fix must produce a single AutofixResult that adds both
    fields, not two conflicting results that overwrite each other."""

    def test_skill_fix_adds_both_fields_at_once(self, temp_dir):
        # Create a plugin with a skill whose frontmatter has neither name nor description
        plugin_dir = temp_dir / "test-plugin"
        plugin_dir.mkdir()

        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(json.dumps({"name": "test-plugin"}))

        skills_dir = plugin_dir / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()

        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nsome-field: value\n---\n\n# My Skill\n")

        context = RepositoryContext(plugin_dir)
        rule = SkillFrontmatterRule()

        violations = rule.check(context)
        assert len(violations) == 2
        messages = {v.message for v in violations}
        assert "Missing 'name' in SKILL.md frontmatter" in messages
        assert "Missing 'description' in SKILL.md frontmatter" in messages

        fixes = rule.fix(context, violations)
        # Must produce exactly one fix, not two conflicting ones
        assert len(fixes) == 1

        fix = fixes[0]
        assert "name: my-skill" in fix.fixed_content
        assert "description: " in fix.fixed_content
        assert len(fix.violations_fixed) == 2

    def test_skill_fix_single_field_still_works(self, temp_dir):
        """Ensure fixing just one missing field still works correctly."""
        plugin_dir = temp_dir / "test-plugin"
        plugin_dir.mkdir()

        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(json.dumps({"name": "test-plugin"}))

        skills_dir = plugin_dir / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()

        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: my-skill\n---\n\n# My Skill\n")

        context = RepositoryContext(plugin_dir)
        rule = SkillFrontmatterRule()

        violations = rule.check(context)
        assert len(violations) == 1
        assert "description" in violations[0].message

        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert "description: " in fixes[0].fixed_content
        assert "name: my-skill" in fixes[0].fixed_content


class TestAgentFixBothFieldsMissing:
    """Regression: when both name and description are missing from agent
    frontmatter, the fix must produce a single AutofixResult that adds both
    fields, not two conflicting results that overwrite each other."""

    def test_agent_fix_adds_both_fields_at_once(self, temp_dir):
        plugin_dir = temp_dir / "test-plugin"
        plugin_dir.mkdir()

        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(json.dumps({"name": "test-plugin"}))

        agents_dir = plugin_dir / "agents"
        agents_dir.mkdir()

        agent_md = agents_dir / "my-agent.md"
        agent_md.write_text("---\nsome-field: value\n---\n\n# My Agent\n")

        context = RepositoryContext(plugin_dir)
        rule = AgentFrontmatterRule()

        violations = rule.check(context)
        assert len(violations) == 2
        messages = {v.message for v in violations}
        assert "Missing 'name' in frontmatter" in messages
        assert "Missing 'description' in frontmatter" in messages

        fixes = rule.fix(context, violations)
        # Must produce exactly one fix, not two conflicting ones
        assert len(fixes) == 1

        fix = fixes[0]
        assert "name: my-agent" in fix.fixed_content
        assert "description: " in fix.fixed_content
        assert len(fix.violations_fixed) == 2

    def test_agent_fix_single_field_still_works(self, temp_dir):
        """Ensure fixing just one missing field still works correctly."""
        plugin_dir = temp_dir / "test-plugin"
        plugin_dir.mkdir()

        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text(json.dumps({"name": "test-plugin"}))

        agents_dir = plugin_dir / "agents"
        agents_dir.mkdir()

        agent_md = agents_dir / "my-agent.md"
        agent_md.write_text("---\nname: my-agent\n---\n\n# My Agent\n")

        context = RepositoryContext(plugin_dir)
        rule = AgentFrontmatterRule()

        violations = rule.check(context)
        assert len(violations) == 1
        assert "description" in violations[0].message

        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert "description: " in fixes[0].fixed_content
        assert "name: my-agent" in fixes[0].fixed_content


def _make_plugin(tmp_path, plugin_name, command_files):
    """Helper: create a minimal plugin with the given command files."""
    plugin_dir = tmp_path / plugin_name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir(exist_ok=True)
    (claude_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_name,
                "description": "test",
                "version": "1.0.0",
                "author": {"name": "Test"},
            }
        )
    )

    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir(exist_ok=True)
    for filename, content in command_files.items():
        (commands_dir / filename).write_text(content)

    return plugin_dir


class TestCommandRenameFix:
    """Regression: CommandNamingRule.fix() must rename files via Path.rename(),
    not write-then-leave-duplicate.  Also guards against data loss on
    case-insensitive filesystems."""

    def test_rename_removes_old_file(self, temp_dir):
        """After applying a rename fix, the old file must not exist."""
        content = "---\ndescription: test\n---\n"
        plugin_dir = _make_plugin(temp_dir, "my-plugin", {"MyCommand.md": content})
        context = RepositoryContext(plugin_dir)
        rule = CommandNamingRule()

        violations = rule.check(context)
        assert len(violations) == 1

        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].rename_from is not None

        applied = Linter.apply_fixes(fixes, confidence=AutofixConfidence.SUGGEST)
        assert len(applied) == 1

        commands_dir = plugin_dir / "commands"
        assert (commands_dir / "my-command.md").exists()
        assert not (commands_dir / "MyCommand.md").exists()
        assert (commands_dir / "my-command.md").read_text() == content

    def test_rename_snake_case(self, temp_dir):
        content = "hello"
        plugin_dir = _make_plugin(temp_dir, "my-plugin", {"do_thing.md": content})
        context = RepositoryContext(plugin_dir)
        rule = CommandNamingRule()

        violations = rule.check(context)
        assert len(violations) == 1

        fixes = rule.fix(context, violations)
        applied = Linter.apply_fixes(fixes, confidence=AutofixConfidence.SUGGEST)
        assert len(applied) == 1

        commands_dir = plugin_dir / "commands"
        assert (commands_dir / "do-thing.md").exists()
        assert not (commands_dir / "do_thing.md").exists()

    def test_no_fix_for_already_kebab(self, temp_dir):
        plugin_dir = _make_plugin(temp_dir, "my-plugin", {"good-name.md": "ok"})
        context = RepositoryContext(plugin_dir)
        rule = CommandNamingRule()

        violations = rule.check(context)
        assert len(violations) == 0

    def test_multiple_bad_names(self, temp_dir):
        plugin_dir = _make_plugin(
            temp_dir,
            "my-plugin",
            {"MyCmd.md": "a", "Another_Cmd.md": "b", "good-cmd.md": "c"},
        )
        context = RepositoryContext(plugin_dir)
        rule = CommandNamingRule()

        violations = rule.check(context)
        assert len(violations) == 2

        fixes = rule.fix(context, violations)
        assert len(fixes) == 2

        applied = Linter.apply_fixes(fixes, confidence=AutofixConfidence.SUGGEST)
        assert len(applied) == 2

        commands_dir = plugin_dir / "commands"
        assert (commands_dir / "my-cmd.md").exists()
        assert (commands_dir / "another-cmd.md").exists()
        assert (commands_dir / "good-cmd.md").exists()
        assert not (commands_dir / "MyCmd.md").exists()
        assert not (commands_dir / "Another_Cmd.md").exists()

    def test_skip_when_target_exists(self, temp_dir):
        """If the target file already exists, the fix should be skipped."""
        plugin_dir = _make_plugin(
            temp_dir,
            "my-plugin",
            {"MyCommand.md": "old", "my-command.md": "existing"},
        )
        context = RepositoryContext(plugin_dir)
        rule = CommandNamingRule()

        violations = rule.check(context)
        assert len(violations) == 1  # Only MyCommand.md is bad

        fixes = rule.fix(context, violations)
        # Should skip because my-command.md already exists
        assert len(fixes) == 0

    def test_apply_rename_skips_missing_source(self, temp_dir):
        """If rename_from no longer exists at apply time, skip silently."""
        src = temp_dir / "old.md"
        dst = temp_dir / "new.md"
        src.write_text("content")

        fix = AutofixResult(
            rule_id="test",
            file_path=dst,
            confidence=AutofixConfidence.SUGGEST,
            original_content="content",
            fixed_content="content",
            description="rename",
            rename_from=src,
        )

        # Remove source before applying
        src.unlink()

        applied = Linter.apply_fixes([fix], confidence=AutofixConfidence.SUGGEST)
        assert len(applied) == 0
        assert not dst.exists()

    def test_apply_rename_skips_existing_target(self, temp_dir):
        """If the target already exists (different file), skip."""
        src = temp_dir / "old.md"
        dst = temp_dir / "new.md"
        src.write_text("old content")
        dst.write_text("existing content")

        fix = AutofixResult(
            rule_id="test",
            file_path=dst,
            confidence=AutofixConfidence.SUGGEST,
            original_content="old content",
            fixed_content="old content",
            description="rename",
            rename_from=src,
        )

        applied = Linter.apply_fixes([fix], confidence=AutofixConfidence.SUGGEST)
        assert len(applied) == 0
        # Both files should be untouched
        assert src.read_text() == "old content"
        assert dst.read_text() == "existing content"

    def test_rename_from_defaults_to_none(self):
        """AutofixResult.rename_from defaults to None for non-rename fixes."""
        fix = AutofixResult(
            rule_id="test",
            file_path=Path("/tmp/test.txt"),
            confidence=AutofixConfidence.SAFE,
            original_content="a",
            fixed_content="b",
            description="not a rename",
        )
        assert fix.rename_from is None

    def test_case_only_rename(self, temp_dir):
        """Case-only rename (e.g. MyCommand.md -> mycommand.md) must work
        on both case-sensitive and case-insensitive filesystems."""
        content = "---\ndescription: test\n---\n"
        plugin_dir = _make_plugin(temp_dir, "my-plugin", {"MyCommand.md": content})
        context = RepositoryContext(plugin_dir)
        rule = CommandNamingRule()

        violations = rule.check(context)
        assert len(violations) == 1

        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].rename_from is not None

        applied = Linter.apply_fixes(fixes, confidence=AutofixConfidence.SUGGEST)
        assert len(applied) == 1

        commands_dir = plugin_dir / "commands"
        # The kebab-case file must exist with correct content
        assert (commands_dir / "my-command.md").exists()
        assert (commands_dir / "my-command.md").read_text() == content

    def test_apply_fix_isolates_oserror(self, temp_dir):
        """One fix raising OSError must not prevent subsequent fixes."""
        good_target = temp_dir / "good.txt"
        good_target.write_text("original")

        # Point the first fix at a path inside a non-existent, read-only
        # parent so write_text raises OSError.
        bad_target = temp_dir / "no-such-dir" / "bad.txt"

        fixes = [
            AutofixResult(
                rule_id="a",
                file_path=bad_target,
                confidence=AutofixConfidence.SAFE,
                original_content="x",
                fixed_content="y",
                description="will fail",
            ),
            AutofixResult(
                rule_id="b",
                file_path=good_target,
                confidence=AutofixConfidence.SAFE,
                original_content="original",
                fixed_content="fixed",
                description="should succeed",
            ),
        ]

        applied = Linter.apply_fixes(fixes)
        # The second fix must still be applied despite the first failing
        assert len(applied) == 1
        assert applied[0].rule_id == "b"
        assert good_target.read_text() == "fixed"
