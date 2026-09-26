"""Pi discovery and CLI regression tests against repository fixtures."""

import os
import json
import shutil
from pathlib import Path

import pytest

from skillsaw.blocks import SkillBlock, SkillRefBlock
from skillsaw.blocks.pi import (
    PiPackageBlock,
    PiSettingsBlock,
    PiSkillBlock,
    PiSkillNode,
    PiPromptBlock,
    PiExtensionNode,
)
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.agentskills.unreferenced_files import (
    AgentSkillUnreferencedFilesRule,
)
from skillsaw.rules.builtin.pi.config_valid import PiConfigValidRule
from skillsaw.rules.builtin.pi.resource_paths import PiResourcePathsRule
from tests.cli_runner import run_cli
from tests.test_integration import run_lint
from skillsaw.utils import invalidate_read_caches

FIXTURES = Path(__file__).parent / "fixtures" / "pi"


def copy_fixture(name, tmp_path):
    root = tmp_path / name
    shutil.copytree(FIXTURES / name, root)
    return root


def paths(context, cls):
    return {str(p.path.relative_to(context.root_path)) for p in context.lint_tree.find(cls)}


def test_package_selection_and_native_skill_dialect(tmp_path):
    root = copy_fixture("package", tmp_path)
    ctx = RepositoryContext(root)
    assert ctx.repo_type is RepositoryType.PI_PACKAGE
    assert paths(ctx, PiSkillBlock) == {
        "custom/skills/flat.md",
        "custom/skills/review/SKILL.md",
        "custom/skills/keep/SKILL.md",
    }
    assert paths(ctx, PiPromptBlock) == {
        "custom/prompts/review.md",
        "custom/prompts/nested/check.md",
    }
    assert paths(ctx, SkillBlock) == {"skills/unselected/SKILL.md", "custom/skills/skip/SKILL.md"}
    assert paths(ctx, PiExtensionNode) == {"extensions/index.ts"}
    assert not ctx.lint_tree_errors


def test_project_relative_paths_and_local_conventions(tmp_path):
    ctx = RepositoryContext(copy_fixture("project", tmp_path))
    assert {RepositoryType.PI, RepositoryType.PI_PACKAGE} <= ctx.repo_types
    assert paths(ctx, PiSkillBlock) == {
        ".pi/skills/flat.md",
        "custom/scan/SKILL.md",
        "local/skills/flat.md",
    }
    assert paths(ctx, PiPromptBlock) == {".pi/prompts/direct.md", "templates/nested/review.md"}
    assert paths(ctx, PiSettingsBlock) == {".pi/settings.json"}
    assert not ctx.lint_tree_errors


def test_empty_manifest_keeps_portable_skills(tmp_path):
    ctx = RepositoryContext(copy_fixture("empty", tmp_path))
    assert not paths(ctx, PiSkillBlock)
    assert paths(ctx, SkillBlock) == {"skills/unused/SKILL.md"}


def test_keyword_only_package_uses_conventions(tmp_path):
    ctx = RepositoryContext(copy_fixture("conventional", tmp_path))
    assert paths(ctx, PiSkillBlock) == {"skills/check/SKILL.md"}
    assert paths(ctx, PiPromptBlock) == {"prompts/nested/review.md"}


def test_dual_package_keeps_portable_skills(tmp_path):
    ctx = RepositoryContext(copy_fixture("dual", tmp_path))
    assert ctx.provenance(ctx.root_path).ecosystems == frozenset({"pi", "claude"})
    assert paths(ctx, SkillBlock) == {"skills/portable/SKILL.md"}
    assert "custom/flat.md" in paths(ctx, PiSkillBlock)


def test_bad_arrays_are_consolidated(tmp_path):
    ctx = RepositoryContext(copy_fixture("invalid", tmp_path))
    violations = PiConfigValidRule().check(ctx)
    assert len(violations) == 2
    assert any("pi.skills" in v.message and "pi.prompts" in v.message for v in violations)
    assert any("packages[0]" in v.message and "packages[1].source" in v.message for v in violations)
    assert not ctx.lint_tree_errors


def test_literal_paths_opt_in_and_globs_are_not_missing(tmp_path):
    ctx = RepositoryContext(copy_fixture("missing", tmp_path))
    violations = PiResourcePathsRule().check(ctx)
    assert len(violations) == 1
    assert "missing" in violations[0].message
    assert "no-match" not in violations[0].message


@pytest.mark.parametrize("fixture", ["package", "project", "conventional", "empty"])
def test_cli_native_pi_metadata_valid(fixture, tmp_path):
    root = copy_fixture(fixture, tmp_path)
    result = run_cli(
        [
            "lint",
            str(root),
            "--rule",
            "pi-config-valid",
            "--rule",
            "pi-skill-valid",
            "--format",
            "json",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert not data["violations"]


def test_cli_invalid_metadata(tmp_path):
    root = copy_fixture("invalid", tmp_path)
    result = run_cli(["lint", str(root), "--rule", "pi-config-valid", "--format", "json"])
    violations = json.loads(result.stdout)["violations"]
    assert len(violations) == 2
    by_file = {Path(v["file_path"]).name: v for v in violations}
    # Pi spreads settings fields unchecked and crashes at startup (pi 0.84.2:
    # TypeError), while readPiManifest drops malformed package.json#pi fields.
    assert "Pi can fail at startup" in by_file["settings.json"]["message"]
    assert "Pi ignores these fields" in by_file["package.json"]["message"]
    assert {v["severity"] for v in violations} == {"warning"}


def test_null_fields_pi_reads_as_absent_are_valid(tmp_path):
    # settings-manager reads top-level resource fields as `?? []`, a package
    # entry's autoload only matters when `=== false`, and readPiManifest drops
    # a null manifest field. pi 0.84.2 loads this fixture's skill and prompt.
    root = copy_fixture("settings-null", tmp_path)
    args = ["lint", str(root), "--rule", "pi-config-valid", "--format", "json"]
    result = run_cli(args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not json.loads(result.stdout)["violations"]

    settings = root / ".pi/settings.json"
    settings.write_text('{"skills": ["../skills"], "packages": null}\n')
    assert not json.loads(run_cli(args).stdout)["violations"]


def test_null_package_filter_still_warns(tmp_path):
    # Unlike a top-level null, a null package filter reaches Pi's filter as
    # null.length, and the loader drops the whole package.
    root = copy_fixture("settings-null", tmp_path)
    (root / ".pi/settings.json").write_text(
        '{"packages": [{"source": "../review-kit", "prompts": null}]}\n'
    )
    result = run_cli(["lint", str(root), "--rule", "pi-config-valid", "--format", "json"])
    (violation,) = json.loads(result.stdout)["violations"]
    assert "packages[0].prompts (expected an array of strings)" in violation["message"]
    assert "Pi can fail at startup" in violation["message"]


def test_unrelated_npm_package_is_not_pi(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"ordinary"}')
    ctx = RepositoryContext(tmp_path)
    assert RepositoryType.PI_PACKAGE not in ctx.repo_types
    assert not paths(ctx, PiPackageBlock)


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX symlinks")
def test_containment_excludes_and_symlink_loop(tmp_path):
    root = copy_fixture("package", tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("Secret outside the lint root.\n")
    (root / "custom/prompts/escape.md").symlink_to(outside)
    (root / "custom/skills/loop").symlink_to(root / "custom/skills", target_is_directory=True)
    ctx = RepositoryContext(root, exclude_patterns=["custom/skills/keep/**"])
    assert "custom/skills/keep/SKILL.md" not in paths(ctx, PiSkillBlock)
    assert "custom/prompts/escape.md" not in paths(ctx, PiPromptBlock)
    assert not ctx.lint_tree_errors


def test_nested_package_and_unrelated_type_override(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copytree(FIXTURES / "package", root / "packages/review")
    ctx = RepositoryContext(root, repo_types={RepositoryType.AGENTS_MD})
    assert ctx.provenance(root / "packages/review").pi
    assert paths(ctx, PiPackageBlock) == {"packages/review/package.json"}
    assert len(paths(ctx, PiSkillBlock)) == 3


def test_forced_conventional_root_keeps_provenance_declarative(tmp_path):
    root = copy_fixture("conventional", tmp_path)
    (root / "package.json").unlink()
    ctx = RepositoryContext(root, repo_types={RepositoryType.PI_PACKAGE})
    assert not ctx.provenance(root).pi
    assert paths(ctx, PiSkillBlock) == {"skills/check/SKILL.md"}
    assert ctx.skill_count == 1
    assert not paths(ctx, SkillBlock)


def test_forced_malformed_package_reports_parse_error(tmp_path):
    (tmp_path / "package.json").write_text('{"pi":')
    ctx = RepositoryContext(tmp_path, repo_types={RepositoryType.PI_PACKAGE})
    violations = PiConfigValidRule().check(ctx)
    assert len(violations) == 1
    assert "JSON" in violations[0].message


def test_project_overrides_filter_autoload(tmp_path):
    root = copy_fixture("project", tmp_path)
    settings = root / ".pi/settings.json"
    data = json.loads(settings.read_text())
    data["prompts"] = ["!*.md", "+prompts/direct.md", "-prompts/direct.md"]
    settings.write_text(json.dumps(data))
    ctx = RepositoryContext(root)
    assert not paths(ctx, PiPromptBlock)


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX symlinks")
def test_manifest_globs_do_not_walk_hidden_or_symlinked_trees(tmp_path):
    root = copy_fixture("package", tmp_path)
    (root / "custom/prompts/.hidden").mkdir()
    (root / "custom/prompts/.hidden/secret.md").write_text("Hidden prompt.\n")
    (root / "custom/prompts/link").symlink_to(root / "custom/skills", target_is_directory=True)
    ctx = RepositoryContext(root)
    assert paths(ctx, PiPromptBlock) == {
        "custom/prompts/review.md",
        "custom/prompts/nested/check.md",
    }


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX symlinks")
def test_explicit_symlink_and_hidden_roots_load_once(tmp_path):
    root = copy_fixture("package", tmp_path)
    (root / ".selected").symlink_to(root / "custom/skills", target_is_directory=True)
    (root / "package.json").write_text(
        json.dumps({"pi": {"skills": [".selected", "custom/skills"]}})
    )
    ctx = RepositoryContext(root)
    assert len(paths(ctx, PiSkillBlock)) == 4
    assert ctx.skill_count == 5
    assert not ctx.lint_tree_errors


def test_ignore_files_and_skill_root_stop_recursion(tmp_path):
    root = copy_fixture("conventional", tmp_path)
    prompts = root / "prompts"
    (prompts / ".fdignore").write_text("nested/\n")
    (root / "skills/.ignore").write_text("check/\n")
    ctx = RepositoryContext(root)
    assert not paths(ctx, PiSkillBlock)
    assert not paths(ctx, PiPromptBlock)
    (root / "skills/.ignore").unlink()
    invalidate_read_caches()
    nested = root / "skills/check/nested"
    nested.mkdir()
    (nested / "SKILL.md").write_text((root / "skills/check/SKILL.md").read_text())
    ctx = RepositoryContext(root)
    assert paths(ctx, PiSkillBlock) == {"skills/check/SKILL.md"}


def test_extension_index_precedence_and_self_reference_never_execute(tmp_path):
    root = copy_fixture("package", tmp_path)
    (root / "extensions/ignored.ts").write_text('throw new Error("Not an entrypoint");')
    ctx = RepositoryContext(root)
    assert paths(ctx, PiExtensionNode) == {"extensions/index.ts"}
    (root / "extensions/package.json").write_text('{"pi":{"extensions":["."]}}')
    invalidate_read_caches()
    ctx = RepositoryContext(root)
    assert paths(ctx, PiExtensionNode) == {"extensions"}
    assert not ctx.lint_tree_errors


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX symlinks")
def test_settings_symlink_outside_checkout_is_not_read(tmp_path):
    root = copy_fixture("project", tmp_path)
    outside = tmp_path / "settings.json"
    outside.write_text('{"skills":["unexpected"]}')
    settings = root / ".pi/settings.json"
    settings.unlink()
    settings.symlink_to(outside)
    ctx = RepositoryContext(root)
    assert not paths(ctx, PiSettingsBlock)
    assert not ctx.pi_package_roots()
    assert not ctx.lint_tree_errors


def test_severity_override_and_json_no_fabricated_line(tmp_path):
    from skillsaw.rule import Severity

    ctx = RepositoryContext(copy_fixture("invalid", tmp_path))
    rule = PiConfigValidRule({"severity": "error"})
    violations = rule.check(ctx)
    assert all(v.severity is Severity.ERROR and v.line is None for v in violations)


def test_cli_native_skill_error_and_content_checks(tmp_path):
    root = copy_fixture("invalid-skill", tmp_path)
    result = run_cli(["lint", str(root), "--rule", "pi-skill-valid", "--format", "json"])
    violations = json.loads(result.stdout)["violations"]
    assert len(violations) == 1
    assert violations[0]["line"] == 2
    prompt = root / "prompts/check.md"
    prompt.parent.mkdir()
    prompt.write_text("Inspect [the contract](missing-contract.md) before reviewing.\n")
    (root / "package.json").write_text('{"pi":{"prompts":["prompts"]}}')
    result = run_cli(
        ["lint", str(root), "--rule", "content-broken-internal-reference", "--format", "json"]
    )
    assert any(
        v["rule_id"] == "content-broken-internal-reference"
        for v in json.loads(result.stdout)["violations"]
    )


def test_nested_other_consumers_keep_portable_skills(tmp_path):
    root = copy_fixture("package", tmp_path)
    for prefix in (".agents/skills", "plugins/child/skills"):
        skill = root / prefix / "portable"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: portable\ndescription: Use when reviewing an API change.\n---\nReview the request contract.\n"
        )
    marker = root / "plugins/child/.claude-plugin"
    marker.mkdir()
    (marker / "plugin.json").write_text('{"name":"child"}')
    ctx = RepositoryContext(root)
    assert {".agents/skills/portable/SKILL.md", "plugins/child/skills/portable/SKILL.md"} <= paths(
        ctx, SkillBlock
    )


def test_installed_package_stores_are_not_authored_packages(tmp_path):
    pi = tmp_path / ".pi"
    pi.mkdir()
    (pi / "settings.json").write_text('{"packages":["git:github.com/example/package"]}')
    shutil.copytree(FIXTURES / "package", pi / "git/example/package")
    ctx = RepositoryContext(tmp_path)
    assert not ctx.pi_package_roots()
    assert not paths(ctx, PiPackageBlock)


def test_excludes_refresh_package_identity(tmp_path):
    root = copy_fixture("package", tmp_path)
    ctx = RepositoryContext(root)
    assert ctx.provenance(root).pi
    ctx.exclude_patterns.append("package.json")
    ctx.apply_excludes()
    assert not ctx.pi_package_roots()
    assert not ctx.provenance(root).pi
    assert RepositoryType.PI_PACKAGE not in ctx.repo_types


def test_disabled_settings_skill_keeps_portable_checks(tmp_path):
    root = copy_fixture("project-filtered", tmp_path)
    ctx = RepositoryContext(root)
    assert not paths(ctx, PiSkillBlock)
    assert paths(ctx, SkillBlock) == {"custom/scan/SKILL.md"}
    result = run_cli(["lint", str(root), "--rule", "agentskill-valid", "--format", "json"])
    assert json.loads(result.stdout)["violations"]


def test_package_sibling_resource_keeps_native_skill_dialect(tmp_path):
    ctx = RepositoryContext(copy_fixture("sibling-resource", tmp_path))
    assert paths(ctx, PiSkillBlock) == {"shared/scan/SKILL.md"}
    assert not paths(ctx, SkillBlock)


@pytest.mark.parametrize("fmt", ["text", "json", "sarif", "html"])
def test_multi_path_reports_native_and_portable_skills(fmt, tmp_path):
    roots = [copy_fixture(name, tmp_path) for name in ("conventional", "empty")]
    result = run_cli(["lint", *map(str, roots), "--rule", "pi-config-valid", "--format", fmt])
    assert result.returncode == 0, result.stderr
    if fmt == "json":
        assert json.loads(result.stdout)["stats"]["skills"] == 2


def test_verbose_skill_paths_match_summary(tmp_path):
    root = copy_fixture("package", tmp_path)
    args = ["lint", str(root), "--rule", "pi-config-valid", "--format", "json"]
    summary = json.loads(run_cli(args).stdout)
    verbose = json.loads(run_cli(args + ["--verbose"]).stdout)
    assert summary["stats"]["skills"] == len(verbose["stats"]["skills"]) == 5


def test_empty_pi_claim_preserves_portable_findings(tmp_path):
    root = copy_fixture("empty", tmp_path)
    args = ["lint", str(root), "--format", "json"]

    def portable_findings():
        return [
            v
            for v in json.loads(run_cli(args).stdout)["violations"]
            if v["rule_id"].startswith("agentskill-")
        ]

    (root / "package.json").unlink()
    before = portable_findings()
    assert before
    for claim in ({"pi": {}}, {"pi": None}):
        (root / "package.json").write_text(json.dumps(claim))
        assert portable_findings() == before


@pytest.mark.skipif(os.name == "nt", reason="Wall-clock regex budget requires SIGALRM")
def test_hostile_patterns_do_not_escape_discovery(tmp_path):
    root = copy_fixture("patterns", tmp_path)
    ctx = RepositoryContext(root)
    assert len(paths(ctx, PiSkillBlock)) == 1
    assert not ctx.lint_tree_errors
    result = run_cli(["lint", str(root), "--rule", "pi-config-valid", "--format", "json"])
    assert result.returncode == 0, result.stderr


def test_nested_ignore_prefixing_matches_pinned_pi_loader(tmp_path):
    root = copy_fixture("conventional", tmp_path)
    nested = root / "prompts/nested"
    (nested / ".gitignore").write_text(
        "# Pi prefixes these patterns with nested/\ndraft-*.md\n!draft-keep.md\n"
    )
    (nested / "draft-drop.md").write_text("Review validation.\n")
    (nested / "draft-keep.md").write_text("Review error responses.\n")
    (nested / "deeper").mkdir()
    (nested / "deeper/draft-visible.md").write_text("Review response schemas.\n")
    ctx = RepositoryContext(root)
    assert paths(ctx, PiPromptBlock) == {
        "prompts/nested/review.md",
        "prompts/nested/draft-keep.md",
        "prompts/nested/deeper/draft-visible.md",
    }


def test_pi_only_package_prose_and_config_roles(tmp_path):
    from skillsaw.blocks import ReadmeBlock, CommandBlock, HooksBlock, SettingsBlock

    ctx = RepositoryContext(copy_fixture("attachment", tmp_path))
    assert paths(ctx, ReadmeBlock) == {"packages/review/README.md"}
    assert paths(ctx, CommandBlock) == {"packages/review/commands/review.md"}
    assert not paths(ctx, HooksBlock)
    assert not paths(ctx, SettingsBlock)


@pytest.mark.parametrize("directory", ["node_modules", "vendor", "venv"])
def test_glob_discovery_prunes_dependency_directories(directory, tmp_path):
    root = copy_fixture("package", tmp_path)
    target = root / directory / "prompts"
    target.mkdir(parents=True)
    (target / "review.md").write_text("Review third-party implementation.\n")
    (root / "package.json").write_text('{"pi":{"prompts":["**/*.md"]}}')
    ctx = RepositoryContext(root)
    assert not any(p.startswith(directory + "/") for p in paths(ctx, PiPromptBlock))


@pytest.mark.parametrize("value", [[], False, None])
def test_nonobject_settings_reports_json_shape(value, tmp_path):
    root = copy_fixture("project", tmp_path)
    (root / ".pi/settings.json").write_text(json.dumps(value))
    violations = PiConfigValidRule().check(RepositoryContext(root))
    assert len(violations) == 1
    assert "Expected a JSON object" in violations[0].message
    assert "package.json" not in violations[0].message


def test_resource_path_diagnostics_redact_userinfo(tmp_path):
    root = copy_fixture("missing", tmp_path)
    (root / "package.json").write_text('{"pi":{"skills":["ftp://user:secret@host/missing"]}}')
    violations = PiResourcePathsRule().check(RepositoryContext(root))
    assert len(violations) == 1
    assert "secret" not in violations[0].message


def test_cli_forced_pi_type_and_primary_type(tmp_path):
    root = copy_fixture("conventional", tmp_path)
    (root / "package.json").unlink()
    result = run_cli(
        ["lint", str(root), "--type", "pi-package", "--rule", "pi-skill-valid", "--format", "json"]
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["stats"]["repo_type"] == "pi-package"


def test_oversized_paths_preserve_valid_siblings(tmp_path):
    ctx = RepositoryContext(copy_fixture("oversized", tmp_path))
    assert paths(ctx, PiSkillBlock) == {"skills/check/SKILL.md"}
    assert not ctx.lint_tree_errors
    assert len(PiResourcePathsRule().check(ctx)) == 2


@pytest.mark.parametrize(
    "entries,expected",
    [
        (["prompts", "*not-present*"], set()),
        (["*not-present*"], {".pi/prompts/direct.md"}),
        (["prompts", "*not-present*", "+prompts/direct.md"], {".pi/prompts/direct.md"}),
        (
            ["prompts", "+prompts/direct.md", "-prompts/direct.md"],
            {".pi/prompts/nested/ignored.md"},
        ),
    ],
)
def test_explicit_settings_candidates_reserve_autoload_identity(entries, expected, tmp_path):
    root = copy_fixture("project", tmp_path)
    settings = root / ".pi/settings.json"
    settings.write_text(json.dumps({"prompts": entries}))
    ctx = RepositoryContext(root)
    assert paths(ctx, PiPromptBlock) == expected


def test_late_manifest_exclusion_restores_portable_validation(tmp_path):
    root = copy_fixture("conventional", tmp_path)
    ctx = RepositoryContext(root)
    assert not paths(ctx, SkillBlock)
    ctx.exclude_patterns.append("package.json")
    ctx.apply_excludes()
    fresh = RepositoryContext(root, exclude_patterns=["package.json"])
    assert paths(ctx, SkillBlock) == paths(fresh, SkillBlock) == {"skills/check/SKILL.md"}
    assert ctx.repo_types == fresh.repo_types
    ctx.exclude_patterns.append("skills/**")
    ctx.apply_excludes()
    assert not paths(ctx, SkillBlock)


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX symlinks")
def test_local_package_symlink_has_canonical_provenance(tmp_path):
    root = copy_fixture("project", tmp_path)
    (root / "linked").symlink_to(root / "local", target_is_directory=True)
    (root / ".pi/settings.json").write_text('{"packages":["../linked"]}')
    ctx = RepositoryContext(root)
    assert ctx.provenance(root / "linked").pi
    assert ctx.provenance(root / "local").pi
    assert any(p.endswith("skills/flat.md") for p in paths(ctx, PiSkillBlock))
    assert not ctx.lint_tree_errors


def test_transient_compile_failure_is_not_cached(monkeypatch):
    from wcmatch import glob

    from skillsaw import pi_patterns
    from skillsaw.timeouts import RegexTimeout

    pi_patterns._compile_glob.cache_clear()
    original = glob.compile
    calls = 0

    def compile_once(pattern, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RegexTimeout("transient load")
        return original(pattern, **kwargs)

    monkeypatch.setattr(glob, "compile", compile_once)
    assert not pi_patterns._globmatch("review.md", "*.md")
    assert pi_patterns._globmatch("review.md", "*.md")
    assert calls == 2
    pi_patterns._compile_glob.cache_clear()


def test_match_timeout_is_contained(monkeypatch):
    from skillsaw import pi_patterns
    from skillsaw.timeouts import RegexTimeout

    class SlowPattern:
        def match(self, value):
            raise RegexTimeout("slow match")

    monkeypatch.setattr(pi_patterns, "_compile_glob", lambda p: SlowPattern())
    assert not pi_patterns._globmatch("review.md", "*.md")


def test_project_theme_autoload_is_shallow(tmp_path):
    from skillsaw.blocks.pi import PiThemeBlock

    ctx = RepositoryContext(copy_fixture("project", tmp_path))
    assert paths(ctx, PiThemeBlock) == {".pi/themes/dark.json"}


def test_multi_path_report_counts_pi_packages(tmp_path):
    roots = [copy_fixture(name, tmp_path) for name in ("conventional", "empty")]
    result = run_cli(["lint", *map(str, roots), "--rule", "pi-config-valid", "--format", "json"])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["stats"]["plugins"] == 2


def test_dual_package_retains_claude_hooks_security(tmp_path):
    from skillsaw.blocks import HooksBlock
    from skillsaw.rules.builtin.hooks.dangerous import HooksDangerousRule

    ctx = RepositoryContext(copy_fixture("dual", tmp_path))
    assert paths(ctx, HooksBlock) == {"hooks/hooks.json"}
    violations = HooksDangerousRule().check(ctx)
    assert any(v.file_path == ctx.root_path / "hooks/hooks.json" for v in violations)


def test_late_cursor_exclusion_preserves_pi_portable_skills(tmp_path):
    root = copy_fixture("dual-cursor", tmp_path)
    ctx = RepositoryContext(root)
    assert ctx.provenance(root).ecosystems == frozenset({"pi", "cursor"})
    ctx.exclude_patterns.append(".cursor-plugin/plugin.json")
    ctx.apply_excludes()
    fresh = RepositoryContext(root, exclude_patterns=[".cursor-plugin/plugin.json"])
    assert paths(ctx, SkillBlock) == paths(fresh, SkillBlock) == {"skills/check/SKILL.md"}
    assert ctx.provenance(root).ecosystems == frozenset({"pi"})


@pytest.mark.parametrize(
    "host,marker,forced",
    [
        ("grok", ".grok/config.toml", None),
        ("antigravity", ".agents/plugins.json", None),
        ("codex", ".agents/plugins/marketplace.json", None),
        (
            "agent",
            ".agents/plugins/marketplace.json",
            {RepositoryType.AGENT_PLUGIN, RepositoryType.AGENTSKILLS},
        ),
    ],
)
def test_late_catalog_exclusion_preserves_surviving_pi_skills(host, marker, forced, tmp_path):
    root = copy_fixture("dual-" + host, tmp_path)
    ctx = RepositoryContext(root, repo_types=forced)
    expected = {"packages/demo/skills/check/SKILL.md"}
    assert paths(ctx, SkillBlock) == expected
    ctx.exclude_patterns.append(marker)
    ctx.apply_excludes()
    fresh = RepositoryContext(root, exclude_patterns=[marker], repo_types=forced)
    assert paths(ctx, SkillBlock) == paths(fresh, SkillBlock) == expected
    ctx.exclude_patterns.append("packages/demo/skills/**")
    ctx.apply_excludes()
    assert not paths(ctx, SkillBlock)


def test_selected_skill_directory_attaches_support_files(tmp_path):
    """A directory-style Pi skill lints its references/ like Agent Skills does.

    Regression: 0.21 attached the selected SKILL.md as a lone block and the
    sibling support prose fell out of the tree (0.20.0 linted it).
    """
    ctx = RepositoryContext(copy_fixture("skill-references", tmp_path))
    assert paths(ctx, PiSkillNode) == {"skills/demo"}
    assert paths(ctx, PiSkillBlock) == {"skills/demo/SKILL.md", "skills/notes.md"}
    assert paths(ctx, SkillRefBlock) == {
        "skills/demo/references/guide.md",
        "skills/demo/references/orphan.md",
    }
    # The entry stays on Pi's dialect: no portable container, no portable block.
    assert not paths(ctx, SkillNode)
    assert not paths(ctx, SkillBlock)
    ref_node = ctx.lint_tree.find(PiSkillNode)[0]
    assert {type(child) for child in ref_node.children} == {PiSkillBlock, SkillRefBlock}
    assert not ctx.lint_tree_errors

    violations = AgentSkillUnreferencedFilesRule().check(ctx)
    assert [str(v.file_path.relative_to(ctx.root_path)) for v in violations] == [
        "skills/demo/references/orphan.md"
    ]


def test_cli_selected_skill_directory_reports_references_and_directory_stats(tmp_path):
    root = copy_fixture("skill-references", tmp_path)
    result = run_lint(root, "--no-custom-rules")
    assert result["rc"] == 0, result["stderr"]
    data = result["out"]
    findings = {(v["rule_id"], v["file_path"], v.get("line")) for v in data["violations"]}
    assert ("content-weak-language", "skills/demo/references/guide.md", 10) in findings
    assert ("agentskill-unreferenced-files", "skills/demo/references/orphan.md", None) in findings
    assert not {rule for rule, _, _ in findings if rule.startswith("agentskill-")} - {
        "agentskill-unreferenced-files"
    }
    # Directory-style skills report as their directory; flat skills as the file.
    assert [str(Path(p).relative_to(root)) for p in data["stats"]["skills"]] == [
        "skills/demo",
        "skills/notes.md",
    ]

    summary = run_lint(root, "--no-custom-rules", verbose=False)["out"]
    assert summary["stats"]["skills"] == 2
