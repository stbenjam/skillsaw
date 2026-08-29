"""Provenance and policy tests for externally sourced lint-tree content."""

from __future__ import annotations

import shutil
from pathlib import Path

from skillsaw import repository_external_content
from skillsaw.blocks import PromptfooPromptBlock
from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import SkillNode
from skillsaw.linter import Linter
from skillsaw.rule import RuleViolation, Severity

FIXTURES = Path(__file__).parent / "fixtures"


def _copy_apm_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "apm-external-content"
    shutil.copytree(FIXTURES / "apm" / "external-content", repo)
    return repo


def test_apm_modules_content_is_tagged_external(tmp_path: Path) -> None:
    repo = _copy_apm_fixture(tmp_path)
    context = RepositoryContext(repo)
    blocks = {block.path.name: block for block in context.lint_tree.find(PromptfooPromptBlock)}

    assert not blocks["promptfooconfig-local.yaml"].in_external_source
    assert blocks["promptfooconfig-vendor.yaml"].externally_sourced
    assert blocks["promptfooconfig-vendor.yaml"].in_external_source
    assert context.externally_sourced_roots() == {(repo / "apm_modules").resolve()}

    skill = context.lint_tree.find(SkillNode)[0]
    assert skill.path.name == "external-skill"
    assert skill.in_external_source


def test_lint_external_content_false_prunes_apm_modules(tmp_path: Path) -> None:
    repo = _copy_apm_fixture(tmp_path)
    config = LinterConfig.default()
    config.lint_external_content = False
    context = RepositoryContext(repo, lint_external_content=False)

    paths = {
        violation.file_path.relative_to(repo)
        for violation in Linter(context, config, rule_ids={"content-weak-language"}).run()
        if violation.file_path is not None
    }

    assert Path("promptfooconfig-local.yaml") in paths
    assert Path("apm_modules/example/vendor-package/promptfooconfig-vendor.yaml") not in paths
    assert all(
        not block.path.is_relative_to(repo / "apm_modules")
        for block in context.lint_tree.content_blocks()
    )


def test_linter_rebuild_and_path_fallback_enforce_external_opt_out(tmp_path: Path) -> None:
    """Programmatic callers and path-only rules cannot bypass the boundary."""
    repo = _copy_apm_fixture(tmp_path)
    config = LinterConfig.default()
    config.lint_external_content = False
    # Deliberately construct the context with its default policy. Linter must
    # apply the config and rebuild a tree that may already have been read.
    context = RepositoryContext(repo)
    assert context.lint_tree.find(SkillNode)

    linter = Linter(context, config)
    relative_external_path = Path("apm_modules/example/vendor-package/promptfooconfig-vendor.yaml")
    path_only = RuleViolation(
        rule_id="synthetic-external-path",
        severity=Severity.WARNING,
        message="external path fallback",
        file_path=relative_external_path,
    )

    assert not context.lint_tree.find(SkillNode)
    assert linter._filter_violations([path_only]) == []


def test_unresolvable_paths_fail_open_without_aborting_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    unresolved = tmp_path / "unresolved"
    context = RepositoryContext(tmp_path)
    context.skills = [unresolved]
    context.reset_external_content_provenance()
    real_safe_resolve = repository_external_content.safe_resolve

    def fail_selected_path(path: Path):
        if path == unresolved:
            return None
        return real_safe_resolve(path)

    monkeypatch.setattr(repository_external_content, "safe_resolve", fail_selected_path)

    assert context.externally_sourced_skill_roots() == set()
    assert not context.is_externally_sourced(unresolved)


def test_fix_never_rewrites_external_apm_content(tmp_path: Path) -> None:
    repo = _copy_apm_fixture(tmp_path)
    skill_file = (
        repo
        / "apm_modules"
        / "example"
        / "vendor-package"
        / "skills"
        / "external-skill"
        / "SKILL.md"
    )
    original = skill_file.read_text()
    linter = Linter(
        RepositoryContext(repo),
        LinterConfig.default(),
        rule_ids={"agentskill-name"},
    )

    violations = linter.run()
    applied, suggested = linter.fix_and_apply()

    assert len(violations) == 1
    assert violations[0].fixable is False
    assert applied == []
    assert suggested == []
    assert skill_file.read_text() == original


def test_apm_compiled_output_is_derived_not_external(tmp_path: Path) -> None:
    repo = tmp_path / "apm-derived"
    (repo / ".apm" / "instructions").mkdir(parents=True)
    (repo / ".github").mkdir()
    (repo / "apm.yml").write_text(
        "name: derived\nversion: 1.0.0\ndescription: Test\ntargets: [copilot]\n"
    )
    (repo / ".apm" / "instructions" / "source.instructions.md").write_text(
        "---\ndescription: Source\n---\n\nRun checks.\n"
    )
    compiled = repo / ".github" / "copilot-instructions.md"
    compiled.write_text("<!-- Generated by APM CLI from .apm/ primitives -->\n\nRun checks.\n")

    block = next(
        block
        for block in RepositoryContext(repo).lint_tree.content_blocks()
        if block.path == compiled
    )

    assert block.content_suppressed
    assert not block.in_external_source
