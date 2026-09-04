"""``codex-plugin-json-valid`` and ``codex-plugin-structure``."""

import json
from pathlib import Path

import pytest

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Severity
from skillsaw.formats.codex import codex_declared_hook_files
from skillsaw.paths import (
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
)
from skillsaw.rules.builtin.codex import (
    CodexMarketplaceJsonValidRule,
    CodexMarketplaceRegistrationRule,
    CodexPluginJsonValidRule,
    CodexPluginStructureRule,
)

from ._helpers import (
    copy_fixture,
    run_rule,
    messages,
    by_severity,
    _codex_plugin_repo,
    _codex_marketplace_repo,
)


class TestPluginJsonValid:
    @pytest.fixture
    def broken(self, tmp_path):
        return copy_fixture("codex/broken", tmp_path)

    def test_parent_traversal_in_manifest_path_is_an_error(self, broken):
        violations = run_rule(CodexPluginJsonValidRule, broken)
        errors = messages(by_severity(violations, Severity.ERROR))
        assert any("'skills'" in m and "'..'" in m for m in errors)

    def test_non_kebab_name_warns(self, broken):
        violations = run_rule(CodexPluginJsonValidRule, broken)
        assert any("escaping_paths" in m and "kebab-case" in m for m in messages(violations))

    def test_missing_recommended_fields_warn(self, broken):
        violations = run_rule(CodexPluginJsonValidRule, broken)
        warnings = messages(by_severity(violations, Severity.WARNING))
        assert "Missing recommended field 'version'" in warnings
        assert "Missing recommended field 'description'" in warnings

    def test_an_oversized_integer_is_invalid_json_not_a_crash(self, tmp_path):
        """On 3.11+ an integer past the digit limit raises bare ValueError,
        not JSONDecodeError — discovery-time reads must report, not abort."""
        repo = tmp_path / "plugin-repo"
        (repo / ".codex-plugin").mkdir(parents=True)
        (repo / ".codex-plugin" / "plugin.json").write_text(
            '{"name":"demo","version":"1.0.0","description":"x","score":' + "1" * 5000 + "}",
            encoding="utf-8",
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert violations and violations[0].message.startswith("Invalid JSON:")

    def test_a_self_symlinked_manifest_with_excludes_does_not_abort(self, tmp_path):
        """The retained missing-manifest violation flows through exclusion
        matching, which must not raise on the symlink loop."""
        repo = tmp_path / "plugin-repo"
        (repo / ".codex-plugin").mkdir(parents=True)
        manifest = repo / ".codex-plugin" / "plugin.json"
        manifest.symlink_to(manifest)

        from skillsaw.config import LinterConfig
        from skillsaw.linter import Linter

        config = LinterConfig.default()
        config.exclude_patterns = ["vendor/**"]
        violations = Linter(RepositoryContext(repo), config).run()  # must not raise
        assert any("plugin.json" in str(v.file_path) for v in violations)

    def test_a_self_symlinked_manifest_does_not_abort_the_lint(self, tmp_path):
        """A plugin.json symlinked to itself must yield a diagnostic, not a
        RuntimeError from Path.resolve() inside the file-read cache that
        aborts RepositoryContext construction entirely."""
        repo = tmp_path / "plugin-repo"
        (repo / ".codex-plugin").mkdir(parents=True)
        manifest = repo / ".codex-plugin" / "plugin.json"
        manifest.symlink_to(manifest)

        RepositoryContext(repo)  # must not raise
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert violations, "expected a manifest diagnostic for the unreadable symlink loop"

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_manifest_constants_are_invalid_json(self, tmp_path, literal):
        """Codex's strict parser rejects the whole manifest; so must we."""
        repo = tmp_path / "plugin-repo"
        (repo / ".codex-plugin").mkdir(parents=True)
        (repo / ".codex-plugin" / "plugin.json").write_text(
            '{"name":"demo","version":"1.0.0","description":"x",'
            '"interface":{"score":' + literal + "}}\n",
            encoding="utf-8",
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert messages(violations) == [f"Invalid JSON: non-finite JSON number: {literal}"]

    def test_inline_mcp_object_inside_an_array_is_conformant(self, tmp_path):
        """``mcpServers: ["./servers.json", {...}]`` is a supported mixed
        declaration — the inline object must not draw a path-string warning."""
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "demo",
                "version": "1.0.0",
                "description": "A mixed MCP declaration.",
                "mcpServers": [
                    "./servers.json",
                    {"inline-one": {"command": "node", "args": ["server.js"]}},
                ],
            },
        )
        (repo / "servers.json").write_text('{"mcpServers": {}}', encoding="utf-8")
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert not any("mcpServers[1]" in m for m in messages(violations)), messages(violations)

    def test_missing_path_target_warns(self, broken):
        violations = run_rule(CodexPluginJsonValidRule, broken)
        warnings = messages(by_severity(violations, Severity.WARNING))
        assert any("interface.logo" in m and "does not exist" in m for m in warnings)

    def test_missing_dot_slash_prefix_is_info_only(self, broken):
        violations = run_rule(CodexPluginJsonValidRule, broken)
        infos = messages(by_severity(violations, Severity.INFO))
        assert any("mcpServers" in m and "should start with './'" in m for m in infos)

    def test_check_paths_exist_can_be_disabled(self, broken):
        violations = run_rule(CodexPluginJsonValidRule, broken, {"check-paths-exist": False})
        assert not any("does not exist" in m for m in messages(violations))

    def test_recommended_fields_configurable(self, broken):
        violations = run_rule(CodexPluginJsonValidRule, broken, {"recommended-fields": []})
        assert not any("Missing recommended field" in m for m in messages(violations))

    def test_missing_name_is_an_error(self, tmp_path):
        repo = _codex_plugin_repo(tmp_path, {"version": "1.0.0", "description": "No name."})
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert "Missing required field 'name'" in messages(by_severity(violations, Severity.ERROR))

    def test_invalid_json_reports_once(self, tmp_path):
        repo = _codex_plugin_repo(tmp_path, {"name": "x"})
        (repo / ".codex-plugin" / "plugin.json").write_text("{not json", encoding="utf-8")
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert len(violations) == 1
        assert violations[0].message.startswith("Invalid JSON")

    def test_version_is_not_required_to_be_semver(self, tmp_path):
        """The Codex docs never constrain ``version`` — do not invent semver."""
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "dated",
                "version": "2026.07",
                "description": "Calendar versioned.",
            },
        )
        assert run_rule(CodexPluginJsonValidRule, repo) == []

    def test_an_inline_mcp_servers_object_is_conformant(self, tmp_path):
        """``plugin-json-spec.md`` types this field "string or object" and
        shows the inline form in a worked example, so it is not a defect."""
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "inline-mcp",
                "version": "1.0.0",
                "description": "Declares its MCP server inline.",
                "mcpServers": {"docs": {"command": "docs-mcp"}},
            },
        )
        assert run_rule(CodexPluginJsonValidRule, repo) == []

    def test_undocumented_path_shapes_still_warn(self, tmp_path):
        """``skills`` is typed as a string alone. Codex mirrors Claude
        Code's loader, so an array is a warning rather than an error."""
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "many-skills",
                "version": "1.0.0",
                "description": "Splits skills across directories.",
                "skills": {"a": "./skills"},
            },
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert by_severity(violations, Severity.ERROR) == []
        assert any("documented as a path string" in m for m in messages(violations))

    def test_array_paths_are_checked_element_by_element(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "many-hooks",
                "version": "1.0.0",
                "description": "Splits hooks across files.",
                "hooks": ["./hooks/a.json", "../escape.json"],
            },
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert any("hooks[1]" in m and "'..'" in m for m in messages(violations))
        assert any("hooks[0]" in m and "does not exist" in m for m in messages(violations))

    def test_empty_path_is_reported(self, tmp_path):
        """ "" resolves to the plugin root, so the existence check would pass."""
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "hollow",
                "version": "1.0.0",
                "description": "Empty skills path.",
                "skills": "",
            },
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert "'skills' is an empty path" in messages(violations)

    def test_inline_hooks_object_is_not_treated_as_a_path(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "inline-hooks",
                "version": "1.0.0",
                "description": "Declares hooks inline, which the spec allows.",
                "hooks": {"hooks": {"SessionStart": []}},
            },
        )
        assert run_rule(CodexPluginJsonValidRule, repo) == []


class TestPluginStructure:
    def test_stray_file_in_manifest_dir_warns(self, tmp_path):
        repo = copy_fixture("codex/broken", tmp_path)
        violations = run_rule(CodexPluginStructureRule, repo)

        assert len(violations) == 1
        assert violations[0].severity is Severity.WARNING
        assert "hooks.json" in violations[0].message
        assert violations[0].file_path.name == "hooks.json"


class TestEmptyNames:
    """``name: ""`` is a missing identifier, not a casing nit."""

    def test_empty_plugin_name_is_an_error(self, tmp_path):
        repo = _codex_plugin_repo(tmp_path, {"name": "", "version": "1.0.0", "description": "x"})
        violations = run_rule(CodexPluginJsonValidRule, repo)

        assert messages(violations) == ["Required field 'name' is an empty string"]
        assert violations[0].severity is Severity.ERROR

    def test_empty_entry_name_is_an_error(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "",
                        "source": {"source": "url", "url": "https://example.com/x.git"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        violations = run_rule(CodexMarketplaceJsonValidRule, repo)

        assert messages(violations) == ["plugins[0] required field 'name' is an empty string"]
        assert violations[0].severity is Severity.ERROR


class TestRecommendedFieldsConfig:
    @pytest.mark.parametrize("bad", [None, 42, "version"])
    def test_a_non_iterable_setting_does_not_crash_the_rule(self, tmp_path, bad):
        repo = _codex_plugin_repo(tmp_path, {"name": "cfg", "version": "1.0.0", "description": "x"})
        assert run_rule(CodexPluginJsonValidRule, repo, {"recommended-fields": bad}) == []


class TestMalformedManifestShapes:
    @pytest.mark.parametrize(
        "manifest,expected",
        [
            ('["not", "an", "object"]', "object"),
            ('{"name": 42, "version": "1.0.0"}', "name"),
            ('{"name": "ok", "version": "1.0.0", "author": 42}', "author"),
            (
                '{"name": "ok", "version": "1.0.0", "interface": "not-an-object"}',
                "interface",
            ),
        ],
    )
    def test_a_bad_field_shape_is_reported(self, tmp_path, manifest, expected):
        repo = tmp_path / "repo"
        (repo / ".codex-plugin").mkdir(parents=True)
        (repo / ".codex-plugin" / "plugin.json").write_text(manifest, encoding="utf-8")

        found = messages(run_rule(CodexPluginJsonValidRule, repo))
        assert any(expected in m for m in found), found


class TestNestedManifestArrays:
    def test_a_nested_array_is_reported_not_silently_dropped(self, tmp_path):
        """The validator flattened recursively; discovery reads one level.

        So the inner path validated clean and never became a HooksBlock —
        executable commands passing every check while reaching no hook rule.
        """
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "nested",
                "version": "1.0.0",
                "description": "x",
                "hooks": [["./custom-hooks.json"]],
            },
        )
        (repo / "custom-hooks.json").write_text(
            json.dumps(
                {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "x"}]}]}}
            ),
            encoding="utf-8",
        )

        found = messages(run_rule(CodexPluginJsonValidRule, repo))
        assert any("documented as a path string" in m for m in found)
        assert codex_declared_hook_files(repo) == []

    def test_a_single_array_level_still_works(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "flat",
                "version": "1.0.0",
                "description": "x",
                "hooks": ["./custom-hooks.json"],
            },
        )
        (repo / "custom-hooks.json").write_text('{"hooks": {}}', encoding="utf-8")

        assert run_rule(CodexPluginJsonValidRule, repo) == []
        assert len(codex_declared_hook_files(repo)) == 1


class TestManifestPathKind:
    """Existing is not usable — the tree follows these by kind."""

    @pytest.mark.parametrize(
        "field,make,expected",
        [
            ("hooks", "dir", "is a directory — this field names a file"),
            ("mcpServers", "dir", "is a directory — this field names a file"),
            ("skills", "file", "is a file — this field names a directory"),
        ],
    )
    def test_the_wrong_kind_is_reported(self, tmp_path, field, make, expected):
        repo = _codex_plugin_repo(
            tmp_path,
            {"name": "kinds", "version": "1.0.0", "description": "x", field: "./thing"},
        )
        if make == "dir":
            (repo / "thing").mkdir()
        else:
            (repo / "thing").write_text("{}", encoding="utf-8")

        found = messages(run_rule(CodexPluginJsonValidRule, repo))
        assert any(expected in m for m in found)

    def test_the_right_kind_passes(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "kinds",
                "version": "1.0.0",
                "description": "x",
                "hooks": "./hooks/hooks.json",
                "skills": "./skills",
            },
        )
        (repo / "hooks").mkdir()
        (repo / "hooks" / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
        (repo / "skills").mkdir()

        assert run_rule(CodexPluginJsonValidRule, repo) == []


class TestMissingPluginManifest:
    """``.codex-plugin/`` is the evidence; the manifest inside can be missing."""

    def test_the_missing_manifest_is_reported(self, tmp_path):
        repo = tmp_path / "no-manifest"
        (repo / ".codex-plugin").mkdir(parents=True)

        context = RepositoryContext(repo)
        assert RepositoryType.CODEX_PLUGIN in context.repo_types

        found = messages(CodexPluginJsonValidRule({}).check(context))
        assert found == [
            "Missing .codex-plugin/plugin.json — Codex reads the plugin manifest from this path"
        ]

    def test_a_directory_in_place_of_the_manifest_is_reported(self, tmp_path):
        repo = tmp_path / "manifest-is-a-dir"
        (repo / ".codex-plugin" / "plugin.json").mkdir(parents=True)

        found = messages(run_rule(CodexPluginJsonValidRule, repo))
        assert any(m.startswith("Missing .codex-plugin/plugin.json") for m in found)

    def test_registration_does_not_pile_on(self, tmp_path):
        """The missing entrypoint is one defect, reported once."""
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": []})
        (repo / "plugins" / "hollow" / ".codex-plugin").mkdir(parents=True)

        assert run_rule(CodexMarketplaceRegistrationRule, repo) == []


class TestSkillsPathNamingTheRoot:
    def test_the_plugin_root_is_a_legal_skills_directory(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {"name": "rooted", "version": "1.0.0", "description": "x", "skills": "./"},
        )
        (repo / "SKILL.md").write_text(
            "---\nname: rooted\ndescription: A skill at the plugin root\n---\n\n# Rooted\n",
            encoding="utf-8",
        )

        assert repo in RepositoryContext(repo).skills

    def test_a_file_valued_field_still_rejects_the_root(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {"name": "rooted", "version": "1.0.0", "description": "x", "hooks": "./"},
        )
        assert codex_declared_hook_files(repo) == []


class TestDriveRelativeWindowsPaths:
    @pytest.mark.parametrize(
        "declared", ["\\Windows\\System32", "\\\\share\\x", "C:\\temp", "/etc/passwd"]
    )
    def test_a_rooted_path_is_reported_on_any_host(self, tmp_path, declared):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "rooted",
                "version": "1.0.0",
                "description": "x",
                "skills": declared,
            },
        )
        found = messages(run_rule(CodexPluginJsonValidRule, repo))
        assert any("absolute" in m.lower() for m in found), found

    @pytest.mark.parametrize("declared", ["./skills", "skills", "a\\b"])
    def test_a_relative_path_is_not(self, tmp_path, declared):
        repo = _codex_plugin_repo(
            tmp_path,
            {"name": "rel", "version": "1.0.0", "description": "x", "skills": declared},
        )
        found = messages(run_rule(CodexPluginJsonValidRule, repo))
        assert not any("absolute" in m.lower() for m in found), found


class TestStatIsGuardedOnManifestPaths:
    """Both the resolve and the ``stat()`` beside it must be guarded —
    the stat is the call that raises on an over-long path.

    Python 3.13+ swallows ``ENAMETOOLONG`` inside ``Path.is_dir()``, so a
    real over-long path cannot express this regression on every supported
    interpreter. The error is injected instead, which is also the honest
    shape of the test: the guard's contract is "any ``OSError`` from a
    manifest-derived path yields ``False``", not "4000 characters".
    """

    @pytest.mark.parametrize(
        "error", [OSError(36, "File name too long"), ValueError("embedded NUL")]
    )
    @pytest.mark.parametrize(
        "fn,predicate",
        [
            (safe_is_dir, "is_dir"),
            (safe_is_file, "is_file"),
            (safe_exists, "exists"),
            (safe_is_symlink, "is_symlink"),
        ],
    )
    def test_a_failing_stat_reads_as_false(self, fn, predicate, error):
        class Exploding:
            def __getattr__(self, name):
                def raise_it():
                    raise error

                return raise_it

        assert fn(Exploding()) is False

    def test_discovery_survives_a_manifest_path_that_cannot_be_stat_d(self, tmp_path, monkeypatch):
        long_path = "./" + "x" * 4000
        repo = _codex_plugin_repo(
            tmp_path,
            {"name": "lp", "version": "1.0.0", "description": "x", "skills": long_path},
        )

        real_is_dir = Path.is_dir

        def exploding_is_dir(self, *args, **kwargs):
            if len(self.name) > 255:
                raise OSError(36, "File name too long")
            return real_is_dir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "is_dir", exploding_is_dir)

        # Construction is what aborts: discovery runs inside ``__init__``,
        # outside the rule-execution-error guard, so an escaping OSError
        # exits 1 with a traceback and reports nothing at all.
        context = RepositoryContext(repo)
        assert context.codex_plugins == [repo]
        assert any(
            "does not exist" in m for m in messages(CodexPluginJsonValidRule({}).check(context))
        )


class TestManifestDirectoryIsOccupied:
    """The reserved name taken by a non-directory is still a Codex plugin."""

    def test_a_regular_file_named_codex_plugin_keeps_the_plugin(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".codex-plugin").write_text("not a directory\n", encoding="utf-8")

        context = RepositoryContext(repo)
        assert context.codex_plugins == [repo]
        assert RepositoryType.CODEX_PLUGIN in context.repo_types
        assert messages(run_rule(CodexPluginJsonValidRule, repo))

    def test_a_dangling_symlink_inside_the_plugin_keeps_the_plugin(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".codex-plugin").symlink_to(repo / "gone")

        assert RepositoryContext(repo).codex_plugins == [repo]

    def test_a_symlink_out_of_the_plugin_is_still_rejected(self, tmp_path):
        outside = tmp_path / "external"
        (outside / ".codex-plugin").mkdir(parents=True)
        (outside / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "external", "version": "1.0.0"}), encoding="utf-8"
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".codex-plugin").symlink_to(outside / ".codex-plugin")

        assert RepositoryContext(repo).codex_plugins == []


class TestKebabCaseRejectsATrailingNewline:
    def test_a_trailing_newline_is_not_kebab_case(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path, {"name": "new-line\n", "version": "1.0.0", "description": "x"}
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        assert any("kebab-case" in m for m in messages(violations))


class TestEvalsBaselineStability:
    def test_wrong_shape_evals_baseline_survives_message_rewording(self, tmp_path):
        """The violation fingerprints on the file's root-line content, so a
        baseline written against an older message keeps suppressing."""
        from skillsaw.baseline import build_baseline, filter_baselined_violations

        skill = tmp_path / "array-evals"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: array-evals\ndescription: Array evals\n---\n", encoding="utf-8"
        )
        (skill / "evals").mkdir()
        (skill / "evals" / "evals.json").write_text('[{"id": "c1"}]', encoding="utf-8")

        from skillsaw.rules.builtin.agentskills import AgentSkillEvalsRule

        context = RepositoryContext(skill)
        found = AgentSkillEvalsRule({}).check(context)
        assert found and found[0].line == 1
        baseline = build_baseline(found, skill, "0.18.0")
        # A reworded message must not un-suppress: fingerprints key on the
        # source line, which is unchanged.
        for v in found:
            v.message = "a differently worded diagnostic"
        remaining, _ = filter_baselined_violations(found, baseline, skill)
        assert remaining == []


class TestInterfaceAssetUris:
    """Interface branding assets (composerIcon, logo, logoDark, screenshots)
    accept remote HTTP/HTTPS URLs and data URIs as well as local paths."""

    def test_remote_urls_are_not_resolved_as_local_paths(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "example-plugin",
                "version": "1.0.0",
                "description": "Example plugin",
                "interface": {
                    "composerIcon": "https://example.com/icon.svg",
                    "logo": "https://example.com/logo.svg",
                    "logoDark": "http://example.com/logo-dark.svg",
                    "screenshots": ["https://example.com/screenshot.png"],
                },
            },
        )
        assert run_rule(CodexPluginJsonValidRule, repo) == []

    def test_data_uri_asset_passes(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "data-plugin",
                "version": "1.0.0",
                "description": "Plugin with data URI icon",
                "interface": {
                    "composerIcon": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjwvc3ZnPg==",
                },
            },
        )
        assert run_rule(CodexPluginJsonValidRule, repo) == []

    @pytest.mark.parametrize(
        "value,expected_fragment",
        [
            ("https://", "URL must include a host"),
            ("http://", "URL must include a host"),
            ("https://[", "is not a valid URL"),
            ("data:", "empty data URI"),
        ],
    )
    def test_malformed_asset_uri_warns(self, tmp_path, value, expected_fragment):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "bad-uri",
                "version": "1.0.0",
                "description": "Malformed URL",
                "interface": {"logo": value},
            },
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        warnings = messages(by_severity(violations, Severity.WARNING))
        assert any("interface.logo" in m and expected_fragment in m for m in warnings)
        assert not any("should start with './'" in m for m in messages(violations))

    def test_unparseable_non_url_falls_through_to_path_validation(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "bad-path",
                "version": "1.0.0",
                "description": "Unparseable path",
                "interface": {"logo": "//["},
            },
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        msg_list = messages(violations)
        assert any("interface.logo" in m and "absolute path" in m for m in msg_list)

    def test_local_interface_asset_paths_receive_containment_and_existence_checks(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "local-assets",
                "version": "1.0.0",
                "description": "Local asset paths",
                "interface": {
                    "logo": "./missing-logo.png",
                    "composerIcon": "assets/icon.png",
                    "logoDark": "../escaping-logo.png",
                },
            },
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        msg_list = messages(violations)
        assert any("interface.logo" in m and "does not exist in the plugin" in m for m in msg_list)
        assert any(
            "interface.composerIcon" in m and "should start with './'" in m for m in msg_list
        )
        assert any("interface.logoDark" in m and "'..'" in m for m in msg_list)

    def test_mixed_screenshots_array(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "mixed-shots",
                "version": "1.0.0",
                "description": "Mixed screenshots",
                "interface": {
                    "screenshots": [
                        "https://example.com/remote.png",
                        "./local-exists.png",
                        "./local-missing.png",
                    ]
                },
            },
        )
        (repo / "local-exists.png").write_text("fake image", encoding="utf-8")
        violations = run_rule(CodexPluginJsonValidRule, repo)
        msg_list = messages(violations)
        assert not any("screenshots[0]" in m for m in msg_list)
        assert not any("screenshots[1]" in m for m in msg_list)
        assert any("screenshots[2]" in m and "does not exist in the plugin" in m for m in msg_list)

    def test_non_interface_path_fields_do_not_accept_urls(self, tmp_path):
        repo = _codex_plugin_repo(
            tmp_path,
            {
                "name": "url-skills",
                "version": "1.0.0",
                "description": "URL in skills",
                "skills": "https://example.com/skills",
            },
        )
        violations = run_rule(CodexPluginJsonValidRule, repo)
        msg_list = messages(violations)
        assert any("'skills'" in m and "does not exist in the plugin" in m for m in msg_list)
