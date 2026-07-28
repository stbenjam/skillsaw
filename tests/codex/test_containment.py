"""Path containment: nothing is read or followed outside its owning root."""

import json
from pathlib import Path

import pytest

from skillsaw.docs.extractor import extract_docs
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.blocks import HooksBlock, SkillRefBlock
from skillsaw.formats.codex import codex_declared_skill_dirs
from skillsaw.paths import escapes_root, safe_resolve
from skillsaw.rules.builtin.codex import CodexMarketplaceJsonValidRule, CodexPluginJsonValidRule
from skillsaw.rules.builtin.plugins.json_required import PluginJsonRequiredRule

from ._helpers import run_rule, messages, _write_plugin, _codex_plugin_repo, _codex_marketplace_repo


class TestSymlinkContainment:
    """A lexically clean path can still leave the root through a symlink."""

    def test_plugin_manifest_path_through_a_symlink_is_rejected(self, tmp_path):
        outside = tmp_path / "outside"
        (outside / "skills").mkdir(parents=True)
        repo = _codex_plugin_repo(tmp_path, {"name": "linky", "skills": "./skills-link"})
        (repo / "skills-link").symlink_to(outside / "skills", target_is_directory=True)

        found = messages(run_rule(CodexPluginJsonValidRule, repo))
        assert any("resolves outside the plugin root" in m for m in found)

    def test_marketplace_source_through_a_symlink_is_rejected(self, tmp_path):
        outside = tmp_path / "outside-plugin"
        _write_plugin(outside, {"name": "elsewhere"})
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "elsewhere",
                        "source": {"source": "local", "path": "./plugins/linked"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        (repo / "plugins").mkdir()
        (repo / "plugins" / "linked").symlink_to(outside, target_is_directory=True)

        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert any("resolves outside the marketplace root" in m for m in found)

    def test_a_contained_relative_path_still_passes(self, tmp_path):
        repo = _codex_plugin_repo(tmp_path, {"name": "fine", "skills": "./skills"})
        (repo / "skills").mkdir()
        assert messages(run_rule(CodexPluginJsonValidRule, repo)) == [
            "Missing recommended field 'version'",
            "Missing recommended field 'description'",
        ]


class TestCatalogContainment:
    def test_a_symlinked_catalog_is_not_discovered(self, tmp_path):
        """The registration autofix writes the catalog back.

        Following a symlink out of the checkout would make `fix --suggest`
        overwrite a file outside the repository.
        """
        outside = tmp_path / "external-catalog.json"
        outside.write_text(json.dumps({"name": "external", "plugins": []}), encoding="utf-8")
        repo = tmp_path / "linked"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / "marketplace.json").symlink_to(outside)

        context = RepositoryContext(repo)
        assert context.codex_marketplace_paths() == []
        assert RepositoryType.CODEX_MARKETPLACE not in context.repo_types

    def test_a_symlinked_hooks_file_is_not_attached(self, tmp_path):
        outside = tmp_path / "external-hooks.json"
        outside.write_text(
            json.dumps(
                {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "x"}]}]}}
            ),
            encoding="utf-8",
        )
        repo = _codex_plugin_repo(
            tmp_path, {"name": "hooky", "version": "1.0.0", "description": "x"}
        )
        (repo / "hooks").mkdir()
        (repo / "hooks" / "hooks.json").symlink_to(outside)

        blocks = RepositoryContext(repo).lint_tree.find(HooksBlock)
        assert blocks == []


class TestRecursiveSkillContainment:
    def test_a_symlinked_child_of_skills_is_not_followed(self, tmp_path):
        """`skills/` may contain a symlink pointing out of the plugin."""
        outside = tmp_path / "outside" / "leaked"
        outside.mkdir(parents=True)
        (outside / "SKILL.md").write_text(
            "---\nname: leaked\ndescription: Outside the plugin entirely\n---\n\n# Leaked\n",
            encoding="utf-8",
        )
        repo = tmp_path / "repo"
        plugin = repo / ".codex" / "plugins" / "helper"
        plugin.mkdir(parents=True)
        _write_plugin(plugin, {"name": "helper", "version": "1.0.0", "description": "x"})
        (plugin / "skills").mkdir()
        (plugin / "skills" / "external").symlink_to(outside, target_is_directory=True)

        assert RepositoryContext(repo).skills == []

    def test_a_real_child_is_still_discovered(self, tmp_path):
        repo = tmp_path / "repo"
        plugin = repo / ".codex" / "plugins" / "helper"
        plugin.mkdir(parents=True)
        _write_plugin(plugin, {"name": "helper", "version": "1.0.0", "description": "x"})
        skill = plugin / "skills" / "real"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: real\ndescription: Genuinely inside the plugin\n---\n\n# Real\n",
            encoding="utf-8",
        )

        assert RepositoryContext(repo).skills == [skill]


class TestEntrypointContainment:
    def test_a_symlinked_skill_md_is_not_followed(self, tmp_path):
        """The directory is contained; the entrypoint file is the escape."""
        outside = tmp_path / "outside.md"
        outside.write_text(
            "---\nname: leaked\ndescription: Outside the plugin\n---\n\n# Leaked\n",
            encoding="utf-8",
        )
        repo = tmp_path / "repo"
        plugin = repo / ".codex" / "plugins" / "helper"
        plugin.mkdir(parents=True)
        _write_plugin(plugin, {"name": "helper", "version": "1.0.0", "description": "x"})
        skill = plugin / "skills" / "sneaky"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").symlink_to(outside)

        assert RepositoryContext(repo).skills == []


class TestCrossPluginContainment:
    def test_a_manifest_symlinked_from_another_plugin_is_rejected(self, tmp_path):
        """Staying inside the repository is not enough — it must stay inside
        *this* plugin, or A is discovered using B's manifest."""
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": []})
        real = _write_plugin(repo / "plugins" / "b", {"name": "b", "version": "1.0.0"})
        victim = repo / "plugins" / "a"
        victim.mkdir(parents=True)
        (victim / ".codex-plugin").symlink_to(real / ".codex-plugin", target_is_directory=True)

        assert RepositoryContext(repo).codex_plugins == [real]


class TestReferenceContainment:
    def test_a_symlinked_reference_is_not_attached(self, tmp_path):
        """SAFE content fixes rewrite reference files in place, so following
        a symlink here would write through it."""
        outside = tmp_path / "outside.md"
        outside.write_text("# External\n\nSome content.\n", encoding="utf-8")
        repo = tmp_path / "repo"
        plugin = repo / ".codex" / "plugins" / "helper"
        plugin.mkdir(parents=True)
        _write_plugin(plugin, {"name": "helper", "version": "1.0.0", "description": "x"})
        skill = plugin / "skills" / "s"
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: s\ndescription: A skill with references\n---\n\n# S\n",
            encoding="utf-8",
        )
        (skill / "references" / "leaked.md").symlink_to(outside)

        blocks = RepositoryContext(repo).lint_tree.find(SkillRefBlock)
        assert blocks == []

    def test_a_real_reference_is_still_attached(self, tmp_path):
        repo = tmp_path / "repo"
        plugin = repo / ".codex" / "plugins" / "helper"
        plugin.mkdir(parents=True)
        _write_plugin(plugin, {"name": "helper", "version": "1.0.0", "description": "x"})
        skill = plugin / "skills" / "s"
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: s\ndescription: A skill with references\n---\n\n# S\n",
            encoding="utf-8",
        )
        (skill / "references" / "real.md").write_text("# Real\n\nInside.\n", encoding="utf-8")

        blocks = RepositoryContext(repo).lint_tree.find(SkillRefBlock)
        assert [b.path.name for b in blocks] == ["real.md"]


class TestEvalContainment:
    """``evals/evals.json`` is read and rewritten — a symlink out of the
    owning plugin is a read and a write outside the checkout."""

    def _skill_with_escaping_evals(self, tmp_path):
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps({"skill_name": "elsewhere"}), encoding="utf-8")
        repo = _codex_plugin_repo(
            tmp_path, {"name": "holder", "version": "1.0.0", "description": "x"}
        )
        skill = repo / "skills" / "worker"
        (skill / "evals").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: worker\ndescription: Does the work for the tests\n---\n\n# Worker\n",
            encoding="utf-8",
        )
        (skill / "evals" / "evals.json").symlink_to(outside)
        return repo, skill

    def test_an_escaping_evals_file_is_not_read(self, tmp_path):
        from skillsaw.rules.builtin.agentskills.evals import AgentSkillEvalsRule

        repo, _ = self._skill_with_escaping_evals(tmp_path)
        context = RepositoryContext(repo)
        assert AgentSkillEvalsRule({}).check(context) == []

    def test_a_contained_evals_file_is_still_validated(self, tmp_path):
        from skillsaw.rules.builtin.agentskills.evals import AgentSkillEvalsRule

        repo = _codex_plugin_repo(
            tmp_path, {"name": "holder", "version": "1.0.0", "description": "x"}
        )
        skill = repo / "skills" / "worker"
        (skill / "evals").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: worker\ndescription: Does the work for the tests\n---\n\n# Worker\n",
            encoding="utf-8",
        )
        (skill / "evals" / "evals.json").write_text("{ not json", encoding="utf-8")

        violations = AgentSkillEvalsRule({}).check(RepositoryContext(repo))
        assert any("Invalid JSON" in m for m in messages(violations))


class TestNestedPluginSkillAttribution:
    def test_a_nested_plugins_skills_are_not_claimed_by_the_root(self, tmp_path):
        """A root that is itself a plugin contains plugins/, so nested skills
        are relative to both roots."""
        repo = _codex_plugin_repo(
            tmp_path, {"name": "root-plugin", "version": "1.0.0", "description": "x"}
        )
        nested = _write_plugin(repo / "plugins" / "nested", {"name": "nested", "version": "1.0.0"})
        skill = nested / "skills" / "inner"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: inner\ndescription: Belongs to the nested plugin\n---\n\n# Inner\n",
            encoding="utf-8",
        )

        docs = extract_docs(RepositoryContext(repo))
        by_name = {p.name: p for p in docs.plugins}
        assert [s.name for s in by_name["nested"].skills] == ["inner"]
        assert by_name["root-plugin"].skills == []


class TestVisiblePluginSkillContainment:
    """Containment through the visible ``plugins/*`` walk — a distinct
    code path from the ``.codex/`` install location, which the directory
    walk skips outright."""

    def test_codex_discovery_does_not_follow_the_symlink(self, tmp_path):
        _, plugin, _ = self._symlinked_skills(tmp_path)
        assert codex_declared_skill_dirs(plugin) == []

    def test_the_agentskills_walk_does_not_follow_the_symlink(self, tmp_path):
        # _discover_skills_in_dir derives a containment boundary from
        # provenance whenever it starts in or descends into a Codex-only
        # directory, so the generic walk honors it too.
        repo, _, outside = self._symlinked_skills(tmp_path)
        discovered = {safe_resolve(p) for p in RepositoryContext(repo).skills}
        assert safe_resolve(outside) not in discovered

    def _symlinked_skills(self, tmp_path):
        outside = tmp_path / "outside" / "skills" / "external"
        outside.mkdir(parents=True)
        (outside / "SKILL.md").write_text(
            "---\nname: external\ndescription: A skill that lives outside the checkout\n---\n\n"
            "# External\n",
            encoding="utf-8",
        )
        repo = tmp_path / "repo"
        plugin = _write_plugin(
            repo / "plugins" / "skilly",
            {
                "name": "skilly",
                "version": "1.0.0",
                "description": "x",
                "skills": "./skills",
            },
        )
        (plugin / "skills").symlink_to(tmp_path / "outside" / "skills")
        return repo, plugin, outside

    def test_a_real_skills_directory_is_still_walked(self, tmp_path):
        repo = tmp_path / "repo"
        plugin = _write_plugin(
            repo / "plugins" / "skilly",
            {
                "name": "skilly",
                "version": "1.0.0",
                "description": "x",
                "skills": "./skills",
            },
        )
        inner = plugin / "skills" / "inner"
        inner.mkdir(parents=True)
        (inner / "SKILL.md").write_text(
            "---\nname: inner\ndescription: A skill that lives inside the plugin\n---\n\n"
            "# Inner\n",
            encoding="utf-8",
        )

        discovered = {safe_resolve(p) for p in RepositoryContext(repo).skills}
        assert safe_resolve(inner) in discovered


class TestSkillReadmeContainment:
    def test_a_readme_symlinked_out_of_the_plugin_is_not_read(self, tmp_path):
        from skillsaw.rules.builtin.agentskills.unreferenced_files import (
            AgentSkillUnreferencedFilesRule,
        )

        outside = tmp_path / "outside-readme.md"
        outside.write_text("See scripts/orphan.py for details.\n", encoding="utf-8")
        repo = _codex_plugin_repo(
            tmp_path, {"name": "holder", "version": "1.0.0", "description": "x"}
        )
        skill = repo / "skills" / "worker"
        (skill / "scripts").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: worker\ndescription: A skill with one bundled script\n---\n\n# Worker\n",
            encoding="utf-8",
        )
        (skill / "scripts" / "orphan.py").write_text("print('hi')\n", encoding="utf-8")
        (skill / "README.md").symlink_to(outside)

        found = messages(AgentSkillUnreferencedFilesRule({}).check(RepositoryContext(repo)))
        assert any(
            "orphan.py" in m for m in found
        ), "an external README must not suppress a finding about a file inside the skill"

    def test_a_real_readme_still_counts_as_a_reference_root(self, tmp_path):
        from skillsaw.rules.builtin.agentskills.unreferenced_files import (
            AgentSkillUnreferencedFilesRule,
        )

        repo = _codex_plugin_repo(
            tmp_path, {"name": "holder", "version": "1.0.0", "description": "x"}
        )
        skill = repo / "skills" / "worker"
        (skill / "scripts").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: worker\ndescription: A skill with one bundled script\n---\n\n# Worker\n",
            encoding="utf-8",
        )
        (skill / "scripts" / "orphan.py").write_text("print('hi')\n", encoding="utf-8")
        (skill / "README.md").write_text(
            "# Worker\n\nSee scripts/orphan.py for details.\n", encoding="utf-8"
        )

        found = messages(AgentSkillUnreferencedFilesRule({}).check(RepositoryContext(repo)))
        assert not any("orphan.py" in m for m in found)


class TestSkillDiscoveryContainment:
    """Every skill-discovery route honors the Codex plugin-root boundary,
    while Claude plugins keep their established uncontained discovery."""

    def test_legacy_plugin_skill_scan_contains_codex_claimed_directories(self, tmp_path):
        """A commands/-marked Codex plugin enters the legacy plugin list,
        whose skill scan predates containment — a skills/ symlink must not
        pull an out-of-checkout SKILL.md into the tree through it."""
        outside = tmp_path / "outside-skill"
        outside.mkdir()
        (outside / "SKILL.md").write_text(
            "---\nname: external\ndescription: Escaped content.\n---\nBody.\n",
            encoding="utf-8",
        )

        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "cx",
                        "source": {"source": "local", "path": "./plugins/cx"},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                        "category": "Productivity",
                    }
                ],
            },
        )
        plugin = repo / "plugins" / "cx"
        (plugin / "commands").mkdir(parents=True)
        (plugin / "commands" / "go.md").write_text(
            "---\ndescription: Run the thing.\n---\nDo it.\n", encoding="utf-8"
        )
        (plugin / "skills").mkdir()
        (plugin / "skills" / "external").symlink_to(outside, target_is_directory=True)

        context = RepositoryContext(repo)
        assert plugin in context.plugins  # the legacy list claimed it
        resolved_outside = outside.resolve()
        assert all(
            s.resolve() != resolved_outside for s in context.skills
        ), "escaping symlinked skill entered discovery uncontained"

    def test_claude_plugin_symlinked_skills_keep_established_discovery(self, tmp_path):
        """The containment above is Codex-only — Claude plugins keep their
        established uncontained skill discovery."""
        outside = tmp_path / "shared-skill"
        outside.mkdir()
        (outside / "SKILL.md").write_text(
            "---\nname: shared\ndescription: Shared content.\n---\nBody.\n",
            encoding="utf-8",
        )

        repo = tmp_path / "claude-repo"
        plugin = repo / "plugins" / "cl"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "cl", "version": "1.0.0", "description": "A plugin."}),
            encoding="utf-8",
        )
        (plugin / "skills").mkdir()
        (plugin / "skills" / "shared").symlink_to(outside, target_is_directory=True)

        context = RepositoryContext(repo)
        resolved_outside = outside.resolve()
        assert any(s.resolve() == resolved_outside for s in context.skills)


class TestNearestOwningPlugin:
    """A plugin nested inside another is the owner of its own content."""

    def test_content_outside_any_plugin_has_no_owner(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path, {"name": "outer", "version": "1.0.0", "description": "x"}
        )
        assert RepositoryContext(repo).codex_plugin_owning(tmp_path / "elsewhere") is None


class TestExemptionUsesContainedDiscovery:
    def test_a_rejected_manifest_does_not_exempt_the_plugin(self, tmp_path):
        """Discovery rejects the symlinked manifest, so no Codex rule covers
        it — the Claude rule must not stand down as well."""
        outside = tmp_path / "external.json"
        outside.write_text(json.dumps({"name": "external"}), encoding="utf-8")
        repo = tmp_path / "repo"
        plugin = repo / "plugins" / "victim"
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / ".codex-plugin" / "plugin.json").symlink_to(outside)
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text("Run it.\n", encoding="utf-8")

        context = RepositoryContext(repo)
        assert context.codex_plugins == []
        assert messages(PluginJsonRequiredRule({}).check(context)) == ["Missing plugin.json"]

    def test_a_real_codex_plugin_is_still_exempt(self, tmp_path):
        repo = tmp_path / "repo"
        plugin = _write_plugin(repo / "plugins" / "codexy", {"name": "codexy", "version": "1.0.0"})
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text("Run it.\n", encoding="utf-8")

        assert PluginJsonRequiredRule({}).check(RepositoryContext(repo)) == []


class TestResolveFailureModes:
    """`Path.resolve()` raises differently across the supported range.

    A symlink loop is ``RuntimeError`` before Python 3.13 and ``OSError``
    from 3.13 on (non-strict mode stopped raising entirely). skillsaw
    supports 3.9-3.14, so the raising branches cannot be reproduced on any
    single interpreter — they are injected instead of simulated with real
    symlinks, which would only exercise whichever branch this runtime has.
    """

    @pytest.mark.parametrize("exc", [RuntimeError, OSError, ValueError])
    def test_safe_resolve_swallows_every_documented_failure(self, monkeypatch, exc):
        def boom(self, *a, **kw):
            raise exc("nope")

        monkeypatch.setattr(Path, "resolve", boom)
        assert safe_resolve(Path("/anything")) is None

    @pytest.mark.parametrize("exc", [RuntimeError, OSError, ValueError])
    def test_escapes_root_fails_closed(self, monkeypatch, tmp_path, exc):
        """Containment cannot be proven, so the check must fail closed."""

        def boom(self, *a, **kw):
            raise exc("nope")

        monkeypatch.setattr(Path, "resolve", boom)
        assert escapes_root("./loop", tmp_path) is True

    @pytest.mark.parametrize("exc", [RuntimeError, OSError, ValueError])
    def test_path_matches_patterns_never_raises(self, monkeypatch, tmp_path, exc):
        """Violation filtering runs this on every reported path, so a raise
        here aborts the lint that was about to report the loop's own
        diagnostic."""
        from skillsaw.context import path_matches_patterns

        root = tmp_path.resolve()

        def boom(self, *a, **kw):
            raise exc("nope")

        monkeypatch.setattr(Path, "resolve", boom)
        assert path_matches_patterns(root / "x", root, ["**/x"]) is False

    @pytest.mark.parametrize("exc", [RuntimeError, OSError, ValueError])
    def test_the_file_read_cache_keys_on_the_unresolved_path(self, monkeypatch, tmp_path, exc):
        """The cache key is computed before the read, so a raise there
        aborts the whole lint from a lookup — while the reader itself
        already diagnoses unreadable input."""
        from skillsaw.utils import read_text
        from skillsaw.rules.builtin.utils import invalidate_read_caches

        target = tmp_path / "note.md"
        target.write_text("body\n", encoding="utf-8")
        invalidate_read_caches()

        def boom(self, *a, **kw):
            raise exc("nope")

        monkeypatch.setattr(Path, "resolve", boom)
        assert read_text(target) == "body\n"
        # Second call takes the hit path under the same unresolved key.
        assert read_text(target) == "body\n"

    def test_a_real_symlink_loop_does_not_abort_discovery(self, tmp_path):
        """Whichever branch this interpreter takes, the lint must survive."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {"name": "cat", "plugins": [{"name": "loopy", "source": "./plugins/loop"}]},
        )
        (repo / "plugins").mkdir()
        a = repo / "plugins" / "loop"
        b = repo / "plugins" / "loop2"
        a.symlink_to(b, target_is_directory=True)
        b.symlink_to(a, target_is_directory=True)

        context = RepositoryContext(repo)  # must not raise
        assert context.codex_plugins == []


class TestDeeplyNestedDocuments:
    """``json`` and ``yaml`` parse nested containers recursively, so a
    document the parser cannot descend raises ``RecursionError`` rather
    than a decode error. Discovery reads these files while
    ``RepositoryContext`` is being constructed, outside the
    rule-execution-error guard, so an escaping exception aborts the whole
    lint with a traceback and reports nothing at all.

    The error is injected rather than provoked with a very deep document.
    Python 3.14 raises on measured stack usage rather than a depth
    counter, so the depth that overflows depends on the thread's stack
    size — a level that overflows on one machine parses cleanly on
    another, and ``sys.setrecursionlimit`` does not constrain the C
    scanner. Injecting states the actual contract: a ``RecursionError``
    from the parser becomes an error string.
    """

    @staticmethod
    def _explode(*_args, **_kwargs):
        raise RecursionError("Stack overflow")

    def test_the_shared_json_reader_returns_an_error(self, tmp_path, monkeypatch):
        import json as json_mod
        from skillsaw.utils import read_json

        target = tmp_path / "deep.json"
        target.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(json_mod, "loads", self._explode)
        assert read_json(target) == (None, "Nesting too deep to parse")

    def test_the_shared_yaml_readers_return_an_error(self, tmp_path, monkeypatch):
        import yaml as yaml_mod
        from ruamel.yaml import YAML as _Ruamel
        from skillsaw.utils import read_yaml, read_yaml_commented

        target = tmp_path / "deep.yaml"
        target.write_text("a: 1\n", encoding="utf-8")
        monkeypatch.setattr(yaml_mod, "safe_load", self._explode)
        assert read_yaml(target) == (None, "Nesting too deep to parse")

        monkeypatch.setattr(_Ruamel, "load", self._explode)
        other = tmp_path / "deep2.yaml"
        other.write_text("a: 1\n", encoding="utf-8")
        assert read_yaml_commented(other) == (None, "Nesting too deep to parse", None)

    def test_an_unparseable_catalog_is_reported_not_raised(self, tmp_path, monkeypatch):
        import skillsaw.utils as utils_mod

        repo = tmp_path / "repo"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / "marketplace.json").write_text(
            '{"name": "cat", "plugins": []}', encoding="utf-8"
        )
        monkeypatch.setattr(utils_mod.json, "loads", self._explode)

        # Construction is the part that aborts without the guard: discovery reads the
        # catalog inside __init__, where no guard can catch the exception.
        context = RepositoryContext(repo)
        found = messages(CodexMarketplaceJsonValidRule({}).check(context))
        assert any("too deep" in m for m in found), found

    def test_an_unparseable_coderabbit_config_does_not_abort_tree_build(
        self, tmp_path, monkeypatch
    ):
        import yaml as yaml_mod
        from skillsaw.rules.builtin.coderabbit.yaml_valid import CoderabbitYamlValidRule

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".coderabbit.yaml").write_text("reviews:\n  profile: chill\n", encoding="utf-8")
        monkeypatch.setattr(yaml_mod, "safe_load", self._explode)

        context = RepositoryContext(repo)
        assert context.lint_tree is not None
        found = messages(CoderabbitYamlValidRule({}).check(context))
        assert any("too deep" in m for m in found), found
