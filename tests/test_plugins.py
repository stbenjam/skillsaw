"""
Unit tests for plugin (entry point) rule loading.

Fake plugins are built as real modules injected into ``sys.modules`` and
referenced by genuine ``importlib.metadata.EntryPoint`` objects; the
discovery seam ``skillsaw.plugins._iter_entry_points`` is monkeypatched to
return them, so everything downstream (EntryPoint.load, rule resolution,
Linter wiring) runs the production code path.
"""

import sys
import types
from importlib.metadata import EntryPoint
from typing import List

import pytest

import skillsaw.plugins as plugins_mod
from skillsaw import Rule, RuleViolation, Severity
from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.plugins import load_plugins


class AlwaysFiresRule(Rule):
    @property
    def rule_id(self) -> str:
        return "plugin-always-fires"

    @property
    def description(self) -> str:
        return "Always reports one violation (test rule)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context) -> List[RuleViolation]:
        return [self.violation("plugin rule fired")]


class QuietRule(Rule):
    @property
    def rule_id(self) -> str:
        return "plugin-quiet"

    @property
    def description(self) -> str:
        return "Never reports (test rule)"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context) -> List[RuleViolation]:
        return []


class AbstractIntermediate(Rule):
    """Abstract on purpose: must be skipped by module scanning."""

    @property
    def description(self) -> str:
        return "intermediate base"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context):
        return []


class ShadowsBuiltinRule(AlwaysFiresRule):
    @property
    def rule_id(self) -> str:
        return "skill-frontmatter"  # collides with a builtin


@pytest.fixture(autouse=True)
def _clear_dist_fallback_cache():
    plugins_mod._dist_by_entry_point.cache_clear()
    yield
    plugins_mod._dist_by_entry_point.cache_clear()


@pytest.fixture
def fake_plugin(monkeypatch):
    """Install a fake plugin module and register entry points for it.

    Returns a function: fake_plugin(value, name="testplug", module_attrs=...)
    """
    created = []

    def _install(value, name="testplug", module_attrs=None, extra_eps=()):
        mod_name = value.split(":")[0]
        if module_attrs is not None:
            module = types.ModuleType(mod_name)
            for attr, val in module_attrs.items():
                setattr(module, attr, val)
            monkeypatch.setitem(sys.modules, mod_name, module)
            created.append(mod_name)
        eps = [EntryPoint(name, value, plugins_mod.ENTRY_POINT_GROUP), *extra_eps]
        monkeypatch.setattr(plugins_mod, "_iter_entry_points", lambda: eps)
        return eps

    return _install


# ---------------------------------------------------------------------------
# Entry point resolution shapes
# ---------------------------------------------------------------------------


def test_module_with_declared_rules(fake_plugin):
    fake_plugin(
        "fake_declared",
        module_attrs={"SKILLSAW_RULES": [AlwaysFiresRule, QuietRule], "Rule": Rule},
    )
    (plugin,) = load_plugins()
    assert plugin.error is None
    assert plugin.rule_classes == [AlwaysFiresRule, QuietRule]


def test_module_scan_without_declaration(fake_plugin):
    fake_plugin(
        "fake_scanned",
        module_attrs={
            "AlwaysFiresRule": AlwaysFiresRule,
            "Rule": Rule,  # the base class must not be collected
            "AbstractIntermediate": AbstractIntermediate,  # nor abstract bases
            "unrelated": object(),
        },
    )
    (plugin,) = load_plugins()
    assert plugin.error is None
    assert plugin.rule_classes == [AlwaysFiresRule]


def test_entry_point_targets_rule_class(fake_plugin):
    fake_plugin(
        "fake_class:AlwaysFiresRule",
        module_attrs={"AlwaysFiresRule": AlwaysFiresRule},
    )
    (plugin,) = load_plugins()
    assert plugin.rule_classes == [AlwaysFiresRule]


def test_entry_point_targets_list(fake_plugin):
    fake_plugin(
        "fake_list:RULES",
        module_attrs={"RULES": [QuietRule, AlwaysFiresRule]},
    )
    (plugin,) = load_plugins()
    assert plugin.rule_classes == [QuietRule, AlwaysFiresRule]


def test_entry_point_targets_factory(fake_plugin):
    fake_plugin(
        "fake_factory:get_rules",
        module_attrs={"get_rules": lambda: [AlwaysFiresRule]},
    )
    (plugin,) = load_plugins()
    assert plugin.rule_classes == [AlwaysFiresRule]


def test_entry_point_targets_abstract_class(fake_plugin):
    """An abstract class must produce a clear error, not get instantiated."""
    fake_plugin(
        "fake_abs:AbstractIntermediate",
        module_attrs={"AbstractIntermediate": AbstractIntermediate},
    )
    (plugin,) = load_plugins()
    assert plugin.error is not None
    assert "not a concrete" in plugin.error


def test_module_scan_survives_raising_getattr(fake_plugin):
    """A PEP 562 module __getattr__ raising for a dir()-listed name is skipped."""

    def _raise(name):
        raise RuntimeError("boom")

    fake_plugin(
        "fake_raising",
        module_attrs={
            "AlwaysFiresRule": AlwaysFiresRule,
            "__getattr__": _raise,
            "__dir__": lambda: ["phantom_name", "AlwaysFiresRule"],
        },
    )
    (plugin,) = load_plugins()
    assert plugin.error is None
    assert plugin.rule_classes == [AlwaysFiresRule]


def test_dist_fallback_when_entry_point_lacks_dist(fake_plugin, monkeypatch):
    """Python 3.9 EntryPoints carry no dist; the distributions() scan recovers it."""
    fake_plugin("fake_distless", module_attrs={"SKILLSAW_RULES": [AlwaysFiresRule]})

    class FakeDist:
        version = "9.9.9"
        metadata = {"Name": "skillsaw-fake"}
        entry_points = [EntryPoint("testplug", "fake_distless", plugins_mod.ENTRY_POINT_GROUP)]

    monkeypatch.setattr(plugins_mod.metadata, "distributions", lambda: [FakeDist()])
    (plugin,) = load_plugins()
    assert plugin.distribution == "skillsaw-fake"
    assert plugin.version == "9.9.9"


def test_entry_point_targets_garbage(fake_plugin):
    fake_plugin("fake_garbage:thing", module_attrs={"thing": 42})
    (plugin,) = load_plugins()
    assert plugin.error is not None
    assert plugin.rule_classes == []


def test_list_with_non_rule_entry(fake_plugin):
    fake_plugin("fake_badlist:RULES", module_attrs={"RULES": [AlwaysFiresRule, "oops"]})
    (plugin,) = load_plugins()
    assert plugin.error is not None
    assert "not a concrete" in plugin.error


def test_missing_module_captured_as_error(fake_plugin):
    fake_plugin("definitely_not_installed_module")
    (plugin,) = load_plugins()
    assert plugin.error is not None
    assert plugin.rule_classes == []


def test_disabled_plugins_are_not_loaded(fake_plugin):
    fake_plugin("definitely_not_installed_module", name="skipme")
    assert load_plugins(disabled={"skipme"}) == []


def test_installed_plugin_names_does_not_import(fake_plugin):
    fake_plugin("definitely_not_installed_module", name="broken")
    # Listing names must not attempt the (failing) import.
    assert plugins_mod.installed_plugin_names() == ["broken"]


# ---------------------------------------------------------------------------
# Linter integration
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n\nRun `make test` before pushing changes.\n",
        encoding="utf-8",
    )
    return tmp_path


def _lint(repo, config=None, **linter_kwargs):
    context = RepositoryContext(repo)
    linter = Linter(context, config or LinterConfig.default(), **linter_kwargs)
    return linter, linter.run()


def test_plugin_rule_runs_and_sets_source(fake_plugin, repo):
    fake_plugin("fake_run", module_attrs={"SKILLSAW_RULES": [AlwaysFiresRule]})
    linter, violations = _lint(repo)
    assert "plugin-always-fires" in {r.rule_id for r in linter.rules}
    fired = [v for v in violations if v.rule_id == "plugin-always-fires"]
    assert len(fired) == 1
    assert fired[0].source == "plugin:testplug"


def test_no_plugins_flag_skips_loading(fake_plugin, repo):
    fake_plugin("fake_noplug", module_attrs={"SKILLSAW_RULES": [AlwaysFiresRule]})
    linter, violations = _lint(repo, no_plugins=True)
    assert "plugin-always-fires" not in {r.rule_id for r in linter.rules}
    assert "plugin-always-fires" not in {v.rule_id for v in violations}


def test_plugins_disabled_in_config(fake_plugin, repo):
    fake_plugin("fake_cfgoff", module_attrs={"SKILLSAW_RULES": [AlwaysFiresRule]})
    config = LinterConfig.default()
    config.plugins_enabled = False
    linter, violations = _lint(repo, config=config)
    assert "plugin-always-fires" not in {r.rule_id for r in linter.rules}


def test_specific_plugin_disabled_in_config(fake_plugin, repo):
    fake_plugin("fake_onedis", module_attrs={"SKILLSAW_RULES": [AlwaysFiresRule]})
    config = LinterConfig.default()
    config.disabled_plugins = ["testplug"]
    linter, violations = _lint(repo, config=config)
    assert "plugin-always-fires" not in {r.rule_id for r in linter.rules}


def test_broken_plugin_surfaces_error_and_lint_continues(fake_plugin, repo):
    fake_plugin("definitely_not_installed_module")
    linter, violations = _lint(repo)
    errors = [v for v in violations if v.rule_id == "plugin-load-error"]
    assert len(errors) == 1
    assert errors[0].severity == Severity.ERROR
    assert "testplug" in errors[0].message
    # Builtin rules still ran despite the broken plugin.
    assert any(getattr(r, "_source", "") == "builtin" for r in linter.rules)


def test_rule_id_collision_with_builtin_is_skipped(fake_plugin, repo):
    fake_plugin("fake_shadow", module_attrs={"SKILLSAW_RULES": [ShadowsBuiltinRule]})
    linter, violations = _lint(repo)
    shadow = [r for r in linter.rules if r.rule_id == "skill-frontmatter"]
    # Only the builtin instance remains.
    assert len(shadow) == 1
    assert getattr(shadow[0], "_source", "builtin") == "builtin"
    warnings = [v for v in violations if v.rule_id == "plugin-load-error"]
    assert len(warnings) == 1
    assert warnings[0].severity == Severity.WARNING


def test_plugin_rule_configurable_via_rules_section(fake_plugin, repo):
    fake_plugin("fake_cfg", module_attrs={"SKILLSAW_RULES": [AlwaysFiresRule]})
    config = LinterConfig.default()
    config.rules["plugin-always-fires"] = {"severity": "error"}
    linter, violations = _lint(repo, config=config)
    fired = [v for v in violations if v.rule_id == "plugin-always-fires"]
    assert fired and fired[0].severity == Severity.ERROR

    config.rules["plugin-always-fires"] = {"enabled": False}
    linter, violations = _lint(repo, config=config)
    assert "plugin-always-fires" not in {r.rule_id for r in linter.rules}


def test_plugin_rule_selectable_and_skippable(fake_plugin, repo):
    fake_plugin("fake_sel", module_attrs={"SKILLSAW_RULES": [AlwaysFiresRule]})
    # --rule accepts a plugin rule id without raising "unknown rule"
    linter, violations = _lint(repo, rule_ids={"plugin-always-fires"})
    assert {r.rule_id for r in linter.rules} == {"plugin-always-fires"}
    # --skip-rule removes it
    linter, violations = _lint(repo, skip_rule_ids={"plugin-always-fires"})
    assert "plugin-always-fires" not in {r.rule_id for r in linter.rules}


def test_scoped_plugin_rule_follows_repo_type_detection(fake_plugin, repo):
    """A plugin rule declaring repo_types only auto-activates on matching repos."""
    from skillsaw.context import RepositoryType

    class MarketplaceOnlyRule(AlwaysFiresRule):
        repo_types = {RepositoryType.MARKETPLACE}

        @property
        def rule_id(self) -> str:
            return "plugin-marketplace-only"

    fake_plugin("fake_scoped", module_attrs={"SKILLSAW_RULES": [MarketplaceOnlyRule]})
    # The plain CLAUDE.md repo is not a marketplace: rule stays off...
    linter, _ = _lint(repo)
    assert "plugin-marketplace-only" not in {r.rule_id for r in linter.rules}
    # ...but an explicit enabled: true still wins.
    config = LinterConfig.default()
    config.rules["plugin-marketplace-only"] = {"enabled": True}
    linter, _ = _lint(repo, config=config)
    assert "plugin-marketplace-only" in {r.rule_id for r in linter.rules}


def test_opt_in_plugin_rule_respects_default_enabled_false(fake_plugin, repo):
    """default_enabled = False makes a plugin rule opt-in, like builtins."""

    class OptInRule(AlwaysFiresRule):
        default_enabled = False

        @property
        def rule_id(self) -> str:
            return "plugin-opt-in"

    fake_plugin("fake_optin", module_attrs={"SKILLSAW_RULES": [OptInRule]})
    linter, _ = _lint(repo)
    assert "plugin-opt-in" not in {r.rule_id for r in linter.rules}

    config = LinterConfig.default()
    config.rules["plugin-opt-in"] = {"enabled": True}
    linter, _ = _lint(repo, config=config)
    assert "plugin-opt-in" in {r.rule_id for r in linter.rules}

    # A non-enabled override on a disabled-by-default rule implies opt-in,
    # matching builtin semantics.
    config = LinterConfig.default()
    config.rules["plugin-opt-in"] = {"severity": "error"}
    linter, _ = _lint(repo, config=config)
    assert "plugin-opt-in" in {r.rule_id for r in linter.rules}


def test_config_entry_for_unloaded_plugin_rule_not_flagged(fake_plugin, repo):
    """With plugins skipped, config entries for their rules are not typos."""
    fake_plugin("fake_lenient", module_attrs={"SKILLSAW_RULES": [AlwaysFiresRule]})
    config = LinterConfig.default()
    config.rules["plugin-always-fires"] = {"severity": "error"}
    linter, violations = _lint(repo, config=config, no_plugins=True)
    assert "invalid-config" not in {v.rule_id for v in violations}


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_config_plugins_mapping(tmp_path):
    cfg = tmp_path / ".skillsaw.yaml"
    cfg.write_text(
        'version: "1.0"\nplugins:\n  enabled: true\n  disable: [one, two]\n',
        encoding="utf-8",
    )
    config = LinterConfig.from_file(cfg)
    assert config.plugins_enabled is True
    assert config.disabled_plugins == ["one", "two"]


def test_config_plugins_bool_shorthand(tmp_path):
    cfg = tmp_path / ".skillsaw.yaml"
    cfg.write_text('version: "1.0"\nplugins: false\n', encoding="utf-8")
    config = LinterConfig.from_file(cfg)
    assert config.plugins_enabled is False


@pytest.mark.parametrize(
    "snippet,message",
    [
        ("plugins: [oops]\n", "'plugins' must be a boolean or a mapping"),
        ("plugins:\n  enabled: 3\n", "'plugins.enabled' must be a boolean"),
        ("plugins:\n  disable: nope\n", "'plugins.disable' must be a list"),
        ("plugins:\n  disable: [1, 2]\n", "'plugins.disable' must be a list"),
    ],
)
def test_config_plugins_invalid(tmp_path, snippet, message):
    cfg = tmp_path / ".skillsaw.yaml"
    cfg.write_text(f'version: "1.0"\n{snippet}', encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        LinterConfig.from_file(cfg)


def test_config_plugins_unknown_subkey_warns(tmp_path):
    cfg = tmp_path / ".skillsaw.yaml"
    cfg.write_text('version: "1.0"\nplugins:\n  bogus: true\n', encoding="utf-8")
    config = LinterConfig.from_file(cfg)
    assert any("plugins" in w and "bogus" in w for w in config.warnings)


# ---------------------------------------------------------------------------
# Extension points: repo types and tree contributors
# ---------------------------------------------------------------------------

from skillsaw.blocks import FileContentBlock  # noqa: E402
from skillsaw.plugins import PluginRepoType  # noqa: E402


def acme_repo_type(**overrides):
    kwargs = dict(
        name="acme",
        description="ACME assistant repository",
        detect=lambda root: (root / "ACME.md").exists(),
        content_paths=["ACME.md"],
    )
    kwargs.update(overrides)
    return PluginRepoType(**kwargs)


@pytest.fixture
def acme_repo(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n\nRun `make test` before pushing changes.\n", encoding="utf-8"
    )
    (tmp_path / "ACME.md").write_text(
        "# ACME instructions\n\nRun `make build` before deploying.\n", encoding="utf-8"
    )
    return tmp_path


def test_repo_type_declared_and_detected(fake_plugin, acme_repo):
    fake_plugin(
        "fake_rt",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_REPO_TYPES": [acme_repo_type()]},
    )
    linter, violations = _lint(acme_repo)
    assert "acme" in linter.context.plugin_repo_types
    assert "acme" in linter.context.repo_type_names()
    assert "plugin-load-error" not in {v.rule_id for v in violations}


def test_repo_type_not_detected_without_marker(fake_plugin, repo):
    fake_plugin(
        "fake_rt_nomark",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_REPO_TYPES": [acme_repo_type()]},
    )
    linter, _ = _lint(repo)
    assert "acme" not in linter.context.plugin_repo_types


def test_repo_type_content_paths_pull_files_into_tree(fake_plugin, acme_repo):
    fake_plugin(
        "fake_rt_content",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_REPO_TYPES": [acme_repo_type()]},
    )
    linter, _ = _lint(acme_repo)
    tree_paths = {node.path.name for node in linter.context.lint_tree.walk()}
    assert "ACME.md" in tree_paths


def test_rule_scoped_to_plugin_repo_type(fake_plugin, acme_repo, tmp_path_factory):
    class AcmeOnlyRule(AlwaysFiresRule):
        repo_types = {"acme"}

        @property
        def rule_id(self) -> str:
            return "plugin-acme-only"

    fake_plugin(
        "fake_rt_scoped",
        module_attrs={
            "SKILLSAW_RULES": [AcmeOnlyRule],
            "SKILLSAW_REPO_TYPES": [acme_repo_type()],
        },
    )
    linter, _ = _lint(acme_repo)
    assert "plugin-acme-only" in {r.rule_id for r in linter.rules}

    plain = tmp_path_factory.mktemp("plain-repo")  # no ACME.md marker
    (plain / "CLAUDE.md").write_text(
        "# Project\n\nRun `make test` before pushing changes.\n", encoding="utf-8"
    )
    linter, _ = _lint(plain)
    assert "plugin-acme-only" not in {r.rule_id for r in linter.rules}


def test_repo_type_colliding_with_builtin_is_skipped(fake_plugin, acme_repo):
    fake_plugin(
        "fake_rt_builtin",
        module_attrs={
            "SKILLSAW_RULES": [],
            "SKILLSAW_REPO_TYPES": [acme_repo_type(name="apm", detect=lambda root: True)],
        },
    )
    linter, violations = _lint(acme_repo)
    assert "apm" not in linter.context.plugin_repo_types
    warnings = [v for v in violations if v.rule_id == "plugin-load-error"]
    assert warnings and "builtin repository type" in warnings[0].message


def test_repo_type_duplicate_across_plugins_first_wins(fake_plugin, monkeypatch, acme_repo):
    import types as types_mod
    from importlib.metadata import EntryPoint

    mod_b = types_mod.ModuleType("fake_rt_dup_b")
    mod_b.SKILLSAW_RULES = []
    mod_b.SKILLSAW_REPO_TYPES = [acme_repo_type(description="duplicate")]
    monkeypatch.setitem(sys.modules, "fake_rt_dup_b", mod_b)
    extra = EntryPoint("secondplug", "fake_rt_dup_b", plugins_mod.ENTRY_POINT_GROUP)

    fake_plugin(
        "fake_rt_dup_a",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_REPO_TYPES": [acme_repo_type()]},
        extra_eps=[extra],
    )
    linter, violations = _lint(acme_repo)
    assert "acme" in linter.context.plugin_repo_types
    warnings = [v for v in violations if v.rule_id == "plugin-load-error"]
    assert warnings and "already provided by plugin 'testplug'" in warnings[0].message


def test_detector_crash_is_isolated(fake_plugin, acme_repo):
    def boom(root):
        raise RuntimeError("boom")

    fake_plugin(
        "fake_rt_crash",
        module_attrs={
            "SKILLSAW_RULES": [],
            "SKILLSAW_REPO_TYPES": [acme_repo_type(detect=boom)],
        },
    )
    linter, violations = _lint(acme_repo)
    assert "acme" not in linter.context.plugin_repo_types
    errors = [v for v in violations if v.rule_id == "plugin-load-error"]
    assert errors and "detector crashed" in errors[0].message
    # Builtin rules still ran.
    assert any(getattr(r, "_source", "") == "builtin" for r in linter.rules)


def test_invalid_repo_type_declaration_fails_plugin(fake_plugin, acme_repo):
    fake_plugin(
        "fake_rt_invalid",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_REPO_TYPES": "nope"},
    )
    (plugin,) = load_plugins()
    assert plugin.error is not None
    assert "SKILLSAW_REPO_TYPES" in plugin.error


def test_invalid_repo_type_name_fails_plugin(fake_plugin):
    fake_plugin(
        "fake_rt_badname",
        module_attrs={
            "SKILLSAW_RULES": [],
            "SKILLSAW_REPO_TYPES": [acme_repo_type(name="Not Kebab")],
        },
    )
    (plugin,) = load_plugins()
    assert plugin.error is not None
    assert "kebab-case" in plugin.error


def test_tree_contributor_adds_block(fake_plugin, acme_repo):
    (acme_repo / "notes.txt").write_text("Deployment notes for the agent.\n", encoding="utf-8")

    def contribute(context, root):
        return [FileContentBlock(path=context.root_path / "notes.txt", category="acme-notes")]

    fake_plugin(
        "fake_contrib",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_TREE_CONTRIBUTORS": [contribute]},
    )
    linter, violations = _lint(acme_repo)
    tree_paths = {node.path.name for node in linter.context.lint_tree.walk()}
    assert "notes.txt" in tree_paths
    assert "plugin-load-error" not in {v.rule_id for v in violations}


def test_tree_contributor_cannot_duplicate_existing_nodes(fake_plugin, acme_repo):
    def contribute(context, root):
        # CLAUDE.md is already in the tree; the seen-set must reject this.
        return [FileContentBlock(path=context.root_path / "CLAUDE.md", category="dup")]

    fake_plugin(
        "fake_contrib_dup",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_TREE_CONTRIBUTORS": [contribute]},
    )
    linter, _ = _lint(acme_repo)
    claude_nodes = [n for n in linter.context.lint_tree.walk() if n.path.name == "CLAUDE.md"]
    assert len(claude_nodes) == 1


def test_tree_contributor_crash_surfaces_violation(fake_plugin, acme_repo):
    def contribute(context, root):
        raise RuntimeError("kaboom")

    fake_plugin(
        "fake_contrib_crash",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_TREE_CONTRIBUTORS": [contribute]},
    )
    linter, violations = _lint(acme_repo)
    errors = [v for v in violations if v.rule_id == "plugin-load-error"]
    assert errors and "tree contributor failed" in errors[0].message
    # The error is consumed: a second run must not duplicate it.
    second = [v for v in linter.run() if v.rule_id == "plugin-load-error"]
    assert second == []


def test_tree_contributor_returning_non_node_surfaces_violation(fake_plugin, acme_repo):
    def contribute(context, root):
        return [42]

    fake_plugin(
        "fake_contrib_garbage",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_TREE_CONTRIBUTORS": [contribute]},
    )
    linter, violations = _lint(acme_repo)
    errors = [v for v in violations if v.rule_id == "plugin-load-error"]
    assert errors and "not a lint tree node" in errors[0].message


def test_invalid_tree_contributors_declaration_fails_plugin(fake_plugin):
    fake_plugin(
        "fake_contrib_invalid",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_TREE_CONTRIBUTORS": [42]},
    )
    (plugin,) = load_plugins()
    assert plugin.error is not None
    assert "SKILLSAW_TREE_CONTRIBUTORS" in plugin.error


def test_tree_contributor_with_broken_path_surfaces_violation(fake_plugin, acme_repo):
    """A contributed node whose path is unusable is a reported failure, not a crash."""

    def contribute(context, root):
        return [FileContentBlock(path=None, category="broken")]

    fake_plugin(
        "fake_contrib_nopath",
        module_attrs={"SKILLSAW_RULES": [], "SKILLSAW_TREE_CONTRIBUTORS": [contribute]},
    )
    linter, violations = _lint(acme_repo)
    errors = [v for v in violations if v.rule_id == "plugin-load-error"]
    assert errors and "tree contributor failed" in errors[0].message


def test_register_extensions_is_idempotent(fake_plugin, acme_repo):
    """Two Linters sharing one context must not duplicate registrations."""

    def contribute(context, root):
        return []

    fake_plugin(
        "fake_reg_twice",
        module_attrs={
            "SKILLSAW_RULES": [],
            "SKILLSAW_REPO_TYPES": [acme_repo_type()],
            "SKILLSAW_TREE_CONTRIBUTORS": [contribute],
        },
    )
    context = RepositoryContext(acme_repo)
    Linter(context, LinterConfig.default())
    Linter(context, LinterConfig.default())
    assert len(context.plugin_tree_contributors) == 1
    assert context.plugin_content_paths == ["ACME.md"]
    # Plugin content paths survive the second Linter's config reset.
    tree_paths = {node.path.name for node in context.lint_tree.walk()}
    assert "ACME.md" in tree_paths
