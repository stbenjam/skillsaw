"""Config-path ownership from Grok Build 1.0.13's live plugin resolver.

Pinned grok-build 72a61251fcffb464bcc687aeb5a998e5a98ec0c9:
resolve_effective_plugins_config merges trusted project paths; PluginsConfig
turns them into raw PathBufs; discovery::collect_plugin loads each directory
without an installer bundle search. Isolated user-config inspect controls
confirm custom skills, absolute/relative paths, empty versus dot, and typed
list rejection. Inspect does not expose the live project's plugin merge.

Static lint models a session launched beside each declaring .grok directory.
It inventories declarations independently of folder/component trust, never
executes the fixture hooks or connects to its HTTP MCP server.
"""

from __future__ import annotations

import json
import shutil

import pytest

from skillsaw.blocks import CommandBlock, GrokMcpBlock, GrokPluginHooksBlock, HooksBlock, SkillBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import GrokPluginConfigNode, GrokPluginNode
from skillsaw.rules.builtin.grok import GrokPluginStructureRule
from tests.grok._helpers import copy_fixture, lint_json, local_catalog, relative, write_catalog

RULE = "grok-plugin-json-valid"
PLUGIN = "packages/review-tools"
CANARY = "packages/convention-tools"
SKILL = f"{PLUGIN}/guides/review-migration/SKILL.md"


def _config(repo, paths, *, directory=None, extra=""):
    path = (directory or repo) / ".grok" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[plugins]\npaths = {json.dumps(paths)}\n{extra}", encoding="utf-8")


def _roots(context):
    return {node.plugin_dir for node in context.lint_tree.find(GrokPluginConfigNode)}


def _assert_inventory(repo, context):
    tree = context.lint_tree
    assert _roots(context) == {repo / PLUGIN, repo / CANARY}
    assert context.provenance(repo / PLUGIN).ecosystems == frozenset({"grok"})
    assert not context.provenance(repo / "packages/unlisted-tools").grok
    assert relative(repo, tree.find(SkillBlock)) == [SKILL]
    assert relative(repo, tree.find(CommandBlock)) == [
        f"{CANARY}/commands/check-docs.md",
        f"{PLUGIN}/prompts/review-plan.md",
    ]
    hooks = tree.find(GrokPluginHooksBlock)
    assert relative(repo, hooks) == [f"{PLUGIN}/config/hooks.json"]
    assert len(hooks[0].events["Stop"][0].handlers) == 1
    assert hooks[0].events["Stop"][0].handlers[0].command == "printf 'Review notes ready\\n'"
    mcp = tree.find(GrokMcpBlock)
    assert relative(repo, mcp) == [f"{PLUGIN}/config/mcp.json"]
    assert mcp[0].raw_data["mcpServers"]["review-docs"]["url"] == (
        "https://docs.example.invalid/mcp"
    )


@pytest.mark.parametrize("forced", [None, RepositoryType.MARKETPLACE, RepositoryType.GROK_PROJECT])
def test_config_claims_keep_custom_skills_hooks_and_mcp_under_type_overrides(tmp_path, forced):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    context = RepositoryContext(repo, repo_types=[forced] if forced else None)

    _assert_inventory(repo, context)
    if forced is None:
        assert RepositoryType.GROK_PLUGIN in context.repo_types
    else:
        assert forced in context.repo_types
    assert GrokPluginStructureRule().check(context) == []


@pytest.mark.integration
@pytest.mark.parametrize("forced", [False, True])
def test_cli_checks_markerless_config_plugin_and_preserves_positive_sibling(tmp_path, forced):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    args = ["--rule", RULE, "--rule", "grok-plugin-structure", "--no-custom-rules", "--no-plugins"]
    if forced:
        args.extend(["--type", "marketplace"])
    clean = lint_json(repo, *args)
    assert clean["violations"] == []
    assert ("marketplace" if forced else "grok-plugin") in clean["stats"]["repo_types"]
    _assert_inventory(repo, RepositoryContext(repo))

    manifest = repo / PLUGIN / "plugin.json"
    data = json.loads(manifest.read_text())
    data["version"] = 42
    manifest.write_text(json.dumps(data), encoding="utf-8")
    broken = lint_json(repo, *args, returncode=1)
    assert len(broken["violations"]) == 1
    violation = broken["violations"][0]
    assert violation["rule_id"] == RULE
    assert violation["file_path"] == f"{PLUGIN}/plugin.json"
    assert violation["severity"] == "error"
    assert "version" in violation["message"]
    assert _roots(RepositoryContext(repo)) == {repo / PLUGIN, repo / CANARY}


@pytest.mark.parametrize("absolute", [False, True])
def test_nested_config_uses_its_project_launch_base_and_never_linter_cwd(
    tmp_path, monkeypatch, absolute
):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    (repo / ".grok/config.toml").unlink()
    project = repo / "services/payments"
    project.mkdir(parents=True)
    # Parent components are ordinary filesystem paths here, not catalog grammar.
    path = str(repo / PLUGIN) if absolute else "../../" + PLUGIN
    _config(repo, [path, "../../" + CANARY], directory=project)
    decoy = tmp_path / "ambient-cwd"
    decoy.mkdir()
    monkeypatch.chdir(decoy)

    _assert_inventory(repo, RepositoryContext(repo))


def test_actual_user_config_inside_checkout_is_still_declaration_evidence(tmp_path, monkeypatch):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    monkeypatch.setenv("HOME", str(repo))
    monkeypatch.setenv("GROK_HOME", str(repo / ".grok"))
    _assert_inventory(repo, RepositoryContext(repo))


@pytest.mark.parametrize("value", ["", "missing", "$PLUGIN_PATH", "~/packages/review-tools"])
def test_unresolved_paths_do_not_claim_the_root_or_unlisted_plugin(tmp_path, monkeypatch, value):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    monkeypatch.setenv("PLUGIN_PATH", str(repo / PLUGIN))
    _config(repo, [value, CANARY])
    context = RepositoryContext(repo, repo_types=[RepositoryType.MARKETPLACE])
    assert _roots(context) == {repo / CANARY}
    assert context.lint_tree.find(SkillBlock) == []
    assert not context.provenance(repo).grok


@pytest.mark.parametrize(
    "paths,extra",
    [
        (42, ""),
        ([PLUGIN, 42], ""),
        ([PLUGIN], "disabled = [42]\n"),
        ([PLUGIN], "enabled = false\n"),
    ],
)
def test_typed_invalid_plugin_table_declares_nothing(tmp_path, paths, extra):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    _config(repo, paths, extra=extra)
    assert _roots(RepositoryContext(repo)) == set()


@pytest.mark.parametrize("value,root_claimed", [(".", True), ("", False)])
def test_root_path_has_one_container_and_no_initialization_recursion(tmp_path, value, root_claimed):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    for child in (repo / PLUGIN).iterdir():
        shutil.move(str(child), repo / child.name)
    _config(repo, [value, CANARY])
    context = RepositoryContext(repo, repo_types=[RepositoryType.MARKETPLACE])
    tree = context.lint_tree
    assert _roots(context) == ({repo, repo / CANARY} if root_claimed else {repo / CANARY})
    assert context.provenance(repo).grok is root_claimed
    assert relative(repo, tree.find(SkillBlock)) == (
        ["guides/review-migration/SKILL.md"] if root_claimed else []
    )
    assert [node.path for node in tree.find(GrokPluginNode)] == [repo / CANARY]
    assert len(tree.find(GrokPluginHooksBlock)) == int(root_claimed)


def test_config_bundle_does_not_load_child_plugins(tmp_path):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    _config(repo, ["packages", CANARY])
    context = RepositoryContext(repo, repo_types=[RepositoryType.MARKETPLACE])
    # The declaration is still diagnosable, but children get no implicit claim.
    assert not context.provenance(repo / PLUGIN).grok
    assert context.lint_tree.find(SkillBlock) == []
    assert context.lint_tree.find(GrokPluginHooksBlock) == []
    assert relative(repo, context.lint_tree.find(CommandBlock)) == [
        f"{CANARY}/commands/check-docs.md"
    ]


@pytest.mark.parametrize(
    "forced,pattern",
    [
        (None, ".grok/config.toml"),
        (None, ".grok/**"),
        (None, "packages"),
        (None, PLUGIN),
        (None, PLUGIN + "/**"),
        (RepositoryType.MARKETPLACE, ".grok/config.toml"),
    ],
)
def test_excludes_remove_config_claims_and_cached_custom_skills(tmp_path, forced, pattern):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    kwargs = {"repo_types": [forced]} if forced else {}
    context = RepositoryContext(repo, **kwargs)
    _assert_inventory(repo, context)
    context.exclude_patterns.append(pattern)
    context.apply_excludes()
    fresh = RepositoryContext(repo, exclude_patterns=[pattern], **kwargs)
    expected = {repo / CANARY} if pattern.startswith(PLUGIN) else set()
    if pattern == PLUGIN + "/**":
        # A subtree glob excludes files below the root, not the root itself.
        expected.add(repo / PLUGIN)
    for candidate in (context, fresh):
        assert _roots(candidate) == expected
        # The fresh default scan may independently find standalone skills
        # after a declaration is excluded. A forced type has no such fallback;
        # cached claim removal also drops the former plugin's skill targets.
        standalone = candidate is fresh and forced is None and pattern.startswith(".grok/")
        assert relative(repo, candidate.lint_tree.find(SkillBlock)) == (
            [SKILL] if standalone else []
        )
        assert candidate.lint_tree.find(GrokPluginHooksBlock) == []
        assert candidate.provenance(repo / PLUGIN).grok is (repo / PLUGIN in expected)


def test_config_exclusion_preserves_independent_catalog_claim_and_installer_advice(tmp_path):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    write_catalog(repo, local_catalog(PLUGIN, CANARY))
    context = RepositoryContext(repo)
    _assert_inventory(repo, context)
    # Commands-only is valid for direct runtime loading but not installation.
    findings = GrokPluginStructureRule().check(context)
    assert len(findings) == 1
    assert findings[0].file_path == repo / CANARY
    assert "Grok installs nothing" in findings[0].message
    context.exclude_patterns.append(".grok/config.toml")
    context.apply_excludes()
    _assert_inventory(repo, context)


def test_config_catalog_and_manifest_claims_attach_content_once(tmp_path):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    write_catalog(repo, local_catalog(PLUGIN, CANARY))
    marker = repo / PLUGIN / ".grok-plugin"
    marker.mkdir()
    shutil.copyfile(repo / PLUGIN / "plugin.json", marker / "plugin.json")
    _config(repo, [PLUGIN, "./" + PLUGIN, str(repo / PLUGIN), CANARY])
    context = RepositoryContext(repo)
    _assert_inventory(repo, context)
    assert len(context.lint_tree.find(GrokPluginNode)) == 2
    assert len(context.lint_tree.find(HooksBlock)) == 1


@pytest.mark.parametrize("escape", ["config", "plugin", "marker", "component"])
def test_symlink_boundaries_do_not_attach_external_content(tmp_path, escape):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    outside = tmp_path / "outside"
    shutil.copytree(repo / PLUGIN, outside)
    if escape == "config":
        config = repo / ".grok/config.toml"
        shutil.copyfile(config, outside / "config.toml")
        config.unlink()
        config.symlink_to(outside / "config.toml")
    elif escape == "plugin":
        shutil.rmtree(repo / PLUGIN)
        (repo / PLUGIN).symlink_to(outside, target_is_directory=True)
    elif escape == "marker":
        (repo / PLUGIN / ".grok-plugin").symlink_to(outside, target_is_directory=True)
    else:
        shutil.rmtree(repo / PLUGIN / "config")
        (repo / PLUGIN / "config").symlink_to(outside / "config", target_is_directory=True)
    context = RepositoryContext(repo)
    expected = set() if escape == "config" else {repo / CANARY}
    if escape == "component":
        expected.add(repo / PLUGIN)
    assert _roots(context) == expected
    assert context.lint_tree.find(GrokPluginHooksBlock) == []
    assert context.lint_tree.find(GrokMcpBlock) == []


@pytest.mark.parametrize("name", ["packages/cash$flow", "~notes", "packages/with space"])
def test_existing_literal_names_are_not_treated_as_expansion_syntax(tmp_path, name):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    target = repo / name
    shutil.move(str(repo / PLUGIN), target)
    _config(repo, [name, CANARY])
    context = RepositoryContext(repo, repo_types=[RepositoryType.MARKETPLACE])
    assert _roots(context) == {target, repo / CANARY}
    assert relative(repo, context.lint_tree.find(SkillBlock)) == [
        f"{name}/guides/review-migration/SKILL.md"
    ]


def test_absolute_external_path_is_not_a_checkout_claim(tmp_path):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    outside = tmp_path / "external-plugin"
    shutil.copytree(repo / PLUGIN, outside)
    _config(repo, [str(outside), CANARY])
    context = RepositoryContext(repo, repo_types=[RepositoryType.MARKETPLACE])
    assert _roots(context) == {repo / CANARY}
    assert context.lint_tree.find(SkillBlock) == []
    assert context.lint_tree.find(HooksBlock) == []


def test_cold_forced_context_keeps_prior_claims_for_exclusion_pruning(tmp_path):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    context = RepositoryContext(repo, repo_types=[RepositoryType.MARKETPLACE])
    # Do not consult the tree or provenance before narrowing exclusions.
    # The constructor must retain the claims that discovered these skills.
    assert context.skills == [repo / PLUGIN / "guides/review-migration"]
    context.exclude_patterns.append(".grok/config.toml")
    context.apply_excludes()
    assert _roots(context) == set()
    assert context.skills == []
    assert context.lint_tree.find(SkillBlock) == []
    assert context.lint_tree.find(GrokPluginHooksBlock) == []


def test_explicit_config_claim_survives_apm_compiled_root_filter(tmp_path):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    target = repo / ".agents/review-tools"
    target.parent.mkdir()
    shutil.move(str(repo / PLUGIN), target)
    _config(repo, [".agents/review-tools", CANARY])
    (repo / "apm.yml").write_text("name: review-workspace\nversion: 1.0.0\ntargets: [codex]\n")
    source = repo / ".apm/instructions/review.instructions.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\napplyTo: '**'\n---\n\nReview migration plans before approval.\n")
    context = RepositoryContext(repo)
    assert context.in_apm_compiled_dir(target)
    assert context.provenance(target).ecosystems == frozenset({"grok"})
    assert _roots(context) == {target, repo / CANARY}
    assert relative(repo, context.lint_tree.find(SkillBlock)) == [
        ".agents/review-tools/guides/review-migration/SKILL.md"
    ]
    assert relative(repo, context.lint_tree.find(GrokPluginHooksBlock)) == [
        ".agents/review-tools/config/hooks.json"
    ]
    assert relative(repo, context.lint_tree.find(GrokMcpBlock)) == [
        ".agents/review-tools/config/mcp.json"
    ]


@pytest.mark.parametrize(
    "exclusions,remaining",
    [
        ([".grok/config.toml"], {"antigravity"}),
        ([".agents/plugins.json"], {"grok"}),
        ([".grok/config.toml", ".agents/plugins.json"], set()),
    ],
)
def test_exclusions_preserve_a_surviving_declared_skill_owner(tmp_path, exclusions, remaining):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    plugin = repo / PLUGIN
    shutil.move(str(plugin / "guides"), plugin / "skills")
    manifest = plugin / "plugin.json"
    data = json.loads(manifest.read_text())
    data["skills"] = "./skills/"
    manifest.write_text(json.dumps(data))
    registry = repo / ".agents/plugins.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps({"entries": [{"path": "packages"}]}))
    context = RepositoryContext(repo, repo_types=[RepositoryType.MARKETPLACE])
    assert context.provenance(plugin).ecosystems == frozenset({"grok", "antigravity"})
    assert relative(repo, context.lint_tree.find(SkillBlock)) == [
        f"{PLUGIN}/skills/review-migration/SKILL.md"
    ]
    context.exclude_patterns.extend(exclusions)
    context.apply_excludes()
    fresh = RepositoryContext(
        repo, repo_types=[RepositoryType.MARKETPLACE], exclude_patterns=exclusions
    )
    for candidate in (context, fresh):
        assert candidate.provenance(plugin).ecosystems == frozenset(remaining)
        assert relative(repo, candidate.lint_tree.find(SkillBlock)) == (
            [f"{PLUGIN}/skills/review-migration/SKILL.md"] if remaining else []
        )


def test_config_exclusion_preserves_portable_root_plugin_skill_under_forced_type(tmp_path):
    repo = copy_fixture("grok/config-plugin-paths", tmp_path)
    for child in (repo / PLUGIN).iterdir():
        shutil.move(str(child), repo / child.name)
    shutil.move(str(repo / "guides"), repo / "skills")
    manifest = repo / "plugin.json"
    data = json.loads(manifest.read_text())
    data["$schema"] = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    data["skills"] = "./skills/"
    manifest.write_text(json.dumps(data))
    _config(repo, ["."])
    context = RepositoryContext(repo, repo_types=[RepositoryType.MARKETPLACE])
    expected = ["skills/review-migration/SKILL.md"]
    assert context.provenance(repo).ecosystems == frozenset({"agent-plugin", "grok"})
    assert relative(repo, context.lint_tree.find(SkillBlock)) == expected
    context.exclude_patterns.append(".grok/config.toml")
    context.apply_excludes()
    fresh = RepositoryContext(
        repo, repo_types=[RepositoryType.MARKETPLACE], exclude_patterns=[".grok/config.toml"]
    )
    for candidate in (context, fresh):
        assert candidate.agent_plugin_roots() == [repo]
        assert candidate.provenance(repo).ecosystems == frozenset({"agent-plugin"})
        assert relative(repo, candidate.lint_tree.find(SkillBlock)) == expected
