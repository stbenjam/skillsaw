"""Skill discovery and the authored/installed enforcement split."""

import pytest

from skillsaw.config import LinterConfig
from skillsaw.docs.extractor import extract_docs
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.linter import Linter
from skillsaw.rule import AutofixConfidence
from skillsaw.rules.builtin.codex import CodexPluginJsonValidRule, CodexPluginStructureRule
from skillsaw.rules.builtin.agentskills.name import AgentSkillNameRule

from ._helpers import copy_fixture, run_rule, _write_plugin, _codex_plugin_repo


class TestDeclaredSkillDirs:
    """Skills reachable only through the manifest.

    Every repo here puts the plugin under ``.codex/plugins/`` on purpose:
    that tree is hidden from the repository-wide skill walk, so the
    manifest is the only route in and a miss here is a real miss.
    """

    @staticmethod
    def _installed(tmp_path, manifest):
        repo = tmp_path / "install-repo"
        plugin = repo / ".codex" / "plugins" / "helper"
        plugin.mkdir(parents=True)
        return repo, _write_plugin(plugin, manifest)

    @staticmethod
    def _write_skill(directory, name):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Does the {name} thing\n---\n\n# {name}\n",
            encoding="utf-8",
        )

    def test_a_nondefault_skills_path_is_discovered(self, tmp_path):
        repo, plugin = self._installed(
            tmp_path,
            {
                "name": "bundler",
                "version": "1.0.0",
                "description": "x",
                "skills": "./bundled",
            },
        )
        skill = plugin / "bundled" / "summarize"
        self._write_skill(skill, "summarize")

        assert RepositoryContext(repo).skills == [skill]

    def test_an_array_of_paths_is_followed(self, tmp_path):
        repo, plugin = self._installed(
            tmp_path,
            {
                "name": "bundler",
                "version": "1.0.0",
                "description": "x",
                "skills": ["./one", "./two"],
            },
        )
        for name in ("one", "two"):
            self._write_skill(plugin / name / f"{name}-skill", f"{name}-skill")

        found = {p.name for p in RepositoryContext(repo).skills}
        assert found == {"one-skill", "two-skill"}

    def test_a_path_naming_one_skill_directly_is_discovered(self, tmp_path):
        repo, plugin = self._installed(
            tmp_path,
            {
                "name": "single",
                "version": "1.0.0",
                "description": "x",
                "skills": "./the-skill",
            },
        )
        self._write_skill(plugin / "the-skill", "the-skill")

        assert RepositoryContext(repo).skills == [plugin / "the-skill"]

    def test_the_default_directory_still_works(self, tmp_path):
        repo, plugin = self._installed(
            tmp_path, {"name": "defaulty", "version": "1.0.0", "description": "x"}
        )
        self._write_skill(plugin / "skills" / "capture", "capture")

        assert RepositoryContext(repo).skills == [plugin / "skills" / "capture"]

    def test_a_path_escaping_the_plugin_is_not_followed(self, tmp_path):
        repo, plugin = self._installed(
            tmp_path,
            {
                "name": "escaper",
                "version": "1.0.0",
                "description": "x",
                "skills": "../leaked",
            },
        )
        self._write_skill(plugin.parent / "leaked" / "outside", "outside")

        assert RepositoryContext(repo).skills == []

    def test_agent_skill_rules_fire_on_a_codex_only_repo(self, tmp_path):
        repo, plugin = self._installed(
            tmp_path,
            {
                "name": "hoster",
                "version": "1.0.0",
                "description": "x",
                "skills": "./bundled",
            },
        )
        self._write_skill(plugin / "bundled" / "Bad_Name", "Bad_Name")

        context = RepositoryContext(repo)
        assert context.repo_types == {RepositoryType.CODEX_PLUGIN}

        config = LinterConfig.default()
        config.version = "99.0.0"
        violations = Linter(context, config=config).run()

        assert any(v.rule_id.startswith("agentskill-") for v in violations)


class TestInstalledPluginEnforcement:
    """`.codex/plugins/*` is content the repository runs, not content it wrote.

    The enforcement split is the whole point: rules about what *executes*
    here keep running, rules about manifest *quality* stand down. A blanket
    exclude would pass the first test and lose the second, which is the
    most valuable thing the Codex support does.
    """

    @pytest.fixture
    def broken(self, tmp_path):
        return copy_fixture("codex/broken", tmp_path)

    def test_manifest_quality_rules_stand_down(self, broken):
        """The fixture's vendor plugin has an absolute skills path, a
        non-kebab name, no version or description, and a dangling logo."""
        for rule_cls in (CodexPluginJsonValidRule, CodexPluginStructureRule):
            reported = [
                v for v in run_rule(rule_cls, broken) if "Vendor_Plugin" in str(v.file_path)
            ]
            assert reported == [], f"{rule_cls.__name__} judged an installed plugin"

    def test_dangerous_hooks_still_fire_there(self, broken):
        """A blanket `.codex/plugins/**` exclude would silence this."""
        config = LinterConfig.default()
        config.version = "99.0.0"
        violations = Linter(RepositoryContext(broken), config=config).run()

        dangerous = [
            v
            for v in violations
            if v.rule_id == "hooks-dangerous" and "Vendor_Plugin" in str(v.file_path)
        ]
        assert dangerous, "installed plugin's hooks were not linted"


class TestInstalledSkillAutofix:
    def test_autofix_does_not_rewrite_an_installed_skill(self, tmp_path):
        """The manifest rules stand down there; the fixer must too."""
        repo = tmp_path / "repo"
        plugin = repo / ".codex" / "plugins" / "vendor"
        plugin.mkdir(parents=True)
        _write_plugin(plugin, {"name": "vendor", "version": "1.0.0", "description": "x"})
        skill = plugin / "skills" / "Bad_Name"
        skill.mkdir(parents=True)
        original = "---\nname: Bad_Name\ndescription: Wrong casing for a skill name\n---\n\n# Bad\n"
        (skill / "SKILL.md").write_text(original, encoding="utf-8")

        context = RepositoryContext(repo)
        rule = AgentSkillNameRule({})
        violations = rule.check(context)
        assert violations, "the check must still report the defect"
        assert rule.fix(context, violations) == []
        assert (skill / "SKILL.md").read_text(encoding="utf-8") == original


class TestInstalledSkillFixabilityIsAdvertisedHonestly:
    def test_a_name_violation_on_an_installed_skill_is_not_marked_fixable(self, tmp_path):
        repo = tmp_path / "repo"
        skill = repo / ".codex" / "plugins" / "vendor" / "skills" / "Bad_Name"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: Bad_Name\ndescription: Vendor skill nobody here authored\n---\n\n# Bad\n",
            encoding="utf-8",
        )
        _write_plugin(
            repo / ".codex" / "plugins" / "vendor",
            {"name": "vendor", "version": "1.0.0"},
        )

        violations = AgentSkillNameRule({}).check(RepositoryContext(repo))
        assert violations
        assert not any(v.fixable for v in violations)

    def test_an_authored_skill_is_still_marked_fixable(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path, {"name": "holder", "version": "1.0.0", "description": "x"}
        )
        skill = repo / "skills" / "Bad_Name"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: Bad_Name\ndescription: A skill this repository authored\n---\n\n# Bad\n",
            encoding="utf-8",
        )

        violations = AgentSkillNameRule({}).check(RepositoryContext(repo))
        assert any(v.fixable for v in violations)


class TestInstalledSkillRenameFix:
    def test_rename_autofix_stands_down_on_an_installed_plugin(self, tmp_path):
        from skillsaw.rules.builtin.agentskills.rename_refs import (
            AgentSkillRenameRefsRule,
        )
        from skillsaw.rules.builtin.agentskills._helpers import _write_renames_manifest

        repo = tmp_path / "repo"
        skill = repo / ".codex" / "plugins" / "vendor" / "skills" / "reader"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: reader\ndescription: Vendor skill referencing old-tool-name\n---\n\n"
            "Delegate to old-tool-name when parsing.\n",
            encoding="utf-8",
        )
        _write_plugin(
            repo / ".codex" / "plugins" / "vendor",
            {"name": "vendor", "version": "1.0.0"},
        )
        _write_renames_manifest(repo, [{"old": "old-tool-name", "new": "new-tool-name"}])

        rule = AgentSkillRenameRefsRule({})
        context = RepositoryContext(repo)
        violations = rule.check(context)
        assert violations, "the stale reference is still worth reporting"
        assert rule.fix(context, violations) == []


class TestInstalledSkillsAreNotRepositoryContent:
    def test_a_personal_installs_skills_are_not_published_as_standalone(self, tmp_path):
        repo = tmp_path / "repo"
        own = repo / "skills" / "mine"
        own.mkdir(parents=True)
        (own / "SKILL.md").write_text(
            "---\nname: mine\ndescription: A skill this repository wrote\n---\n\n# Mine\n",
            encoding="utf-8",
        )
        vendor = repo / ".codex" / "plugins" / "vendor"
        _write_plugin(vendor, {"name": "vendor", "version": "1.0.0"})
        theirs = vendor / "skills" / "theirs"
        theirs.mkdir(parents=True)
        (theirs / "SKILL.md").write_text(
            "---\nname: theirs\ndescription: A skill somebody else wrote\n---\n\n# Theirs\n",
            encoding="utf-8",
        )

        docs = extract_docs(RepositoryContext(repo))
        assert [s.name for s in docs.skills] == ["mine"]


class TestVendorManagedContentIsNeverRewritten:
    """No rule's fix() rewrites content under .codex/plugins/. The
    stand-down is drawn in the linter, so it covers the generic content-*
    fixers and any rule added later."""

    def _repo_with_installed_skill(self, tmp_path):
        repo = tmp_path / "repo"
        vendor = repo / ".codex" / "plugins" / "vendor"
        _write_plugin(vendor, {"name": "vendor", "version": "1.0.0"})
        skill = vendor / "skills" / "helper"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: helper\ndescription: A vendor skill that mentions a bundled file\n---\n\n"
            "# Helper\n\nConsult references/notes.md before answering.\n",
            encoding="utf-8",
        )
        (skill / "references").mkdir()
        (skill / "references" / "notes.md").write_text("# Notes\n", encoding="utf-8")
        return repo, skill / "SKILL.md"

    def test_no_fix_targets_an_installed_skill(self, tmp_path):
        repo, skill_md = self._repo_with_installed_skill(tmp_path)
        before = skill_md.read_text(encoding="utf-8")

        linter = Linter(RepositoryContext(repo), LinterConfig.default())
        applied, suggested = linter.fix_and_apply(confidence=AutofixConfidence.SUGGEST)

        assert [f.file_path for f in applied if f.file_path == skill_md] == []
        assert skill_md.read_text(encoding="utf-8") == before

    def test_violations_on_installed_content_are_not_advertised_as_fixable(self, tmp_path):
        repo, skill_md = self._repo_with_installed_skill(tmp_path)
        violations = Linter(RepositoryContext(repo), LinterConfig.default()).run()
        on_skill = [v for v in violations if v.file_path == skill_md]
        assert on_skill, "the vendor skill should still be linted"
        assert not any(v.fixable for v in on_skill)

    def test_an_authored_skill_is_still_fixed(self, tmp_path):
        repo = tmp_path / "repo"
        skill = repo / "skills" / "helper"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: helper\ndescription: A skill this repository wrote itself\n---\n\n"
            "# Helper\n\nConsult references/notes.md before answering.\n",
            encoding="utf-8",
        )
        (skill / "references").mkdir()
        (skill / "references" / "notes.md").write_text("# Notes\n", encoding="utf-8")

        linter = Linter(RepositoryContext(repo), LinterConfig.default())
        applied, _ = linter.fix_and_apply(confidence=AutofixConfidence.SUGGEST)
        assert any(f.file_path == skill / "SKILL.md" for f in applied)
