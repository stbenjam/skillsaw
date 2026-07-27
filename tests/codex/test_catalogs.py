"""Catalog membership across multiple and sibling catalogs."""

import json

import pytest

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formatters.json_fmt import format_json
from skillsaw.formatters.sarif import format_sarif
from skillsaw.rules.builtin.codex import (
    CodexMarketplaceJsonValidRule,
    CodexMarketplaceRegistrationRule,
    CodexOpenAIMetadataRule,
    CodexPluginJsonValidRule,
)
from skillsaw.rules.builtin.marketplace.json_valid import MarketplaceJsonValidRule

from ._helpers import run_rule, messages, _write_plugin, _codex_marketplace_repo


class TestCrossedRegistration:
    """A name/path pair belongs to one entry, not two."""

    def test_a_crossed_entry_does_not_cover_both_plugins(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        # b's name against a's directory: neither plugin is
                        # fully registered, and b is not installable at all.
                        "name": "b",
                        "source": {"source": "local", "path": "./plugins/a"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        _write_plugin(repo / "plugins" / "a", {"name": "a", "version": "1.0.0"})
        _write_plugin(repo / "plugins" / "b", {"name": "b", "version": "1.0.0"})

        found = messages(run_rule(CodexMarketplaceRegistrationRule, repo))
        # b is not silent — but "not registered" would be factually wrong
        # (the name is right there in the catalog), so the accurate
        # listed-but-unresolved diagnostic fires instead.
        assert any("Plugin 'b' is listed" in m and "does not resolve" in m for m in found), found
        assert any("does not match the plugin manifest name" in m for m in found)

    def test_manifest_credentials_are_redacted_from_every_echo_site(self, tmp_path):
        """A user:token@host URL pasted into any path-valued field must not
        reach JSON or SARIF output — reports are uploaded as CI artifacts."""
        secret = "ghp_BARELEAK123456"  # notsecret
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "leaky",
                "plugins": [
                    {
                        "name": "bare",
                        "source": {
                            "source": "local",
                            "path": f"./https://ci-bot:{secret}@registry.example.com/z",
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        plugin = _write_plugin(
            repo / "plugins" / "plug",
            {
                "name": "plug",
                "version": "1.0.0",
                "description": "x",
                "skills": f"./https://u:{secret}@example.com/skills",
            },
        )
        skill = plugin / "skills" / "leaky-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: leaky-skill\ndescription: A skill that leaks\n---\n",
            encoding="utf-8",
        )
        (skill / "agents").mkdir()
        (skill / "agents" / "openai.yaml").write_text(
            f"interface:\n  icon_small: ./https://u:{secret}@example.com/i.png\n",
            encoding="utf-8",
        )

        # A second entry carrying the secret through fields the other rules
        # echo: a name (kebab warning), a source path, and an escape
        # sequence, so the terminal-control assertion below has a live
        # payload.
        catalog = repo / ".agents" / "plugins" / "marketplace.json"
        data = json.loads(catalog.read_text(encoding="utf-8"))
        data["plugins"].append(
            {
                # The escape sequence rides in the name (control-char
                # strip); the credential rides in the URL-shaped path
                # (userinfo redaction) — names are identifiers, not
                # credential carriers, and are echoed as written.
                "name": "Bad_Name\x1b[31m",
                "source": {"source": "local", "path": f"./u:{secret}@host.example/x"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        )
        catalog.write_text(json.dumps(data), encoding="utf-8")
        from skillsaw.utils import invalidate_read_caches

        invalidate_read_caches(catalog)

        context = RepositoryContext(repo)
        # Every message every Codex rule produces — not an enumerated
        # branch list, which is how the leaking site keeps being the one
        # absent from the fixture.
        from skillsaw.rules.builtin.codex import (
            CodexMarketplaceJsonValidRule as _MJV,
            CodexPluginStructureRule as _PS,
        )

        rules = [
            CodexMarketplaceRegistrationRule({}),
            CodexPluginJsonValidRule({}),
            CodexOpenAIMetadataRule({}),
            _MJV({}),
            _PS({}),
        ]
        violations = [v for rule in rules for v in rule.check(context)]
        assert violations, "expected echo-site violations to exercise redaction"
        for v in violations:
            assert secret not in v.message, v.message
            assert "\x1b" not in v.message, v.message
        # A pasted JWT is far longer than any redaction cap — the bound
        # itself was the escape hatch.
        long_secret = "eyJ" + "b" * 400  # notsecret
        from skillsaw.rules.builtin.codex._helpers import safe_display

        assert long_secret not in safe_display(f"https://u:{long_secret}@h/p")

        assert secret not in format_json(violations, context, rules, "0.18.0")
        assert secret not in format_sarif(violations, context, rules, "0.18.0")
        # The locator survives redaction — only the userinfo is stripped.
        assert any("[redacted]@" in v.message for v in violations)

    def test_dual_distribution_by_remote_entry_is_not_an_error(self, tmp_path):
        """The standard dual-distribution layout: the catalog lists the
        plugin by name with a REMOTE source while the same plugin ships
        locally. A remote entry registers the plugin, so reporting it as
        unregistered is wrong."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "my-tool",
                        "source": {"source": "url", "url": "https://example.com/my-tool.git"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        _write_plugin(
            repo / "plugins" / "my-tool",
            {"name": "my-tool", "version": "1.0.0", "description": "A tool."},
        )
        # Remote entries register by name, so the local copy is covered.
        assert run_rule(CodexMarketplaceRegistrationRule, repo) == []

    def test_dual_distribution_by_symlink_is_silent(self, tmp_path):
        """The other observed dual-distribution shape: plugins/<name> is a
        symlink back to the repository root, which is itself the plugin."""
        repo = tmp_path / "marketplace-repo"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": "cat",
                    "plugins": [
                        {
                            "name": "self-tool",
                            "source": {"source": "local", "path": "./plugins/self-tool"},
                            "policy": {
                                "installation": "AVAILABLE",
                                "authentication": "ON_INSTALL",
                            },
                            "category": "Productivity",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (repo / ".codex-plugin").mkdir()
        (repo / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "self-tool", "version": "1.0.0", "description": "Self."}),
            encoding="utf-8",
        )
        (repo / "plugins").mkdir()
        (repo / "plugins" / "self-tool").symlink_to(repo, target_is_directory=True)

        found = run_rule(CodexMarketplaceRegistrationRule, repo)
        assert not any("not registered" in v.message for v in found), messages(found)

    def test_a_remote_entry_still_registers_by_name(self, tmp_path):
        """Remote sources name no directory here, so the name is all there is."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "a",
                        "source": {"source": "url", "url": "https://example.com/a.git"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        _write_plugin(repo / "plugins" / "a", {"name": "a", "version": "1.0.0"})

        assert run_rule(CodexMarketplaceRegistrationRule, repo) == []


class TestCrossCatalogDuplicateNames:
    def test_two_catalogs_claiming_one_name_is_reported(self, tmp_path):
        """Codex aggregates the catalogs, and docs writes one page per name."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "primary",
                "plugins": [
                    {
                        "name": "shared",
                        "source": {"source": "local", "path": "./plugins/one"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        (repo / ".agents" / "plugins" / "api_marketplace.json").write_text(
            json.dumps(
                {
                    "name": "secondary",
                    "plugins": [
                        {
                            "name": "shared",
                            "source": {"source": "local", "path": "./plugins/two"},
                            "policy": {
                                "installation": "AVAILABLE",
                                "authentication": "ON_USE",
                            },
                            "category": "Productivity",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        _write_plugin(repo / "plugins" / "one", {"name": "shared", "version": "1.0.0"})
        _write_plugin(repo / "plugins" / "two", {"name": "shared", "version": "1.0.0"})

        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        duplicates = [m for m in found if "duplicate plugin name 'shared'" in m]
        assert len(duplicates) == 1
        assert "marketplace.json" in duplicates[0], "the other catalog was not named"

    def test_the_same_plugin_listed_in_both_catalogs_is_not_a_duplicate(self, tmp_path):
        """A second listing of one source is a curated view, not a defect.

        Real catalogs split their index across sibling files and list a
        plugin in both. Codex resolves either entry to the same plugin, so
        there is nothing ambiguous to report.
        """
        entry = {
            "name": "shared",
            "source": {"source": "local", "path": "./plugins/one"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
            "category": "Productivity",
        }
        repo = _codex_marketplace_repo(tmp_path, {"name": "primary", "plugins": [entry]})
        (repo / ".agents" / "plugins" / "api_marketplace.json").write_text(
            json.dumps({"name": "secondary", "plugins": [entry]}), encoding="utf-8"
        )
        _write_plugin(repo / "plugins" / "one", {"name": "shared", "version": "1.0.0"})

        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert not any("duplicate plugin name" in m for m in found)

    def test_the_single_catalog_message_is_unchanged(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "same",
                        "source": {"source": "url", "url": "https://example.com/a.git"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ]
                * 2,
            },
        )
        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert "plugins[1] duplicate plugin name 'same' (first defined at plugins[0])" in found


class TestMalformedSourceRegistersNothing:
    """An entry with no resolvable source names no installable plugin."""

    @pytest.mark.parametrize(
        "source",
        [
            {"source": "local"},
            {"source": "local", "path": ""},
            {"source": "typo", "url": "https://example.com"},
            42,
        ],
    )
    def test_a_malformed_entry_does_not_cover_a_real_directory(self, tmp_path, source):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [{"name": "one", "source": source}],
            },
        )
        _write_plugin(repo / "plugins" / "one", {"name": "one", "version": "1.0.0"})

        violations = run_rule(CodexMarketplaceRegistrationRule, repo)
        assert any("not registered" in m for m in messages(violations))


class TestDanglingCatalogSymlink:
    def test_it_is_still_reported(self, tmp_path):
        repo = tmp_path / "dangling"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / "marketplace.json").symlink_to(repo / "missing.json")

        context = RepositoryContext(repo)
        assert RepositoryType.CODEX_MARKETPLACE in context.repo_types
        assert messages(CodexMarketplaceJsonValidRule({}).check(context))


class TestSiblingCatalogNameBoundary:
    @pytest.mark.parametrize("name", ["api_marketplace.json", "api-marketplace.json"])
    def test_a_qualified_catalog_name_is_taken_on_existence(self, tmp_path, name):
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": []})
        (repo / ".agents" / "plugins" / name).write_text("{ not json", encoding="utf-8")

        paths = {p.name for p in RepositoryContext(repo).codex_marketplace_paths()}
        assert name in paths

    def test_an_unrelated_name_still_has_to_duck_type(self, tmp_path):
        repo = _codex_marketplace_repo(tmp_path, {"name": "cat", "plugins": []})
        (repo / ".agents" / "plugins" / "notamarketplace.json").write_text(
            "{ not json", encoding="utf-8"
        )

        paths = {p.name for p in RepositoryContext(repo).codex_marketplace_paths()}
        assert "notamarketplace.json" not in paths


class TestSiblingOnlyCatalogExempts:
    """``openai/plugins`` splits its listing, so a repository whose only
    catalog is a sibling is no less a Codex marketplace."""

    def _repo(self, tmp_path, filename):
        repo = tmp_path / "repo"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / filename).write_text(
            json.dumps({"name": "cat", "plugins": []}), encoding="utf-8"
        )
        _write_plugin(repo / "plugins" / "one", {"name": "one", "version": "1.0.0"})
        return repo

    @pytest.mark.parametrize("filename", ["marketplace.json", "api_marketplace.json"])
    def test_no_claude_marketplace_is_demanded(self, tmp_path, filename):
        repo = self._repo(tmp_path, filename)
        assert MarketplaceJsonValidRule({}).check(RepositoryContext(repo)) == []

    @pytest.mark.parametrize("filename", ["marketplace.json", "api_marketplace.json"])
    def test_the_same_holds_under_an_explicit_type(self, tmp_path, filename):
        """The probe must not read the discovery gate, which `--type` closes."""
        repo = self._repo(tmp_path, filename)
        forced = RepositoryContext(repo, repo_types={RepositoryType.MARKETPLACE})
        assert MarketplaceJsonValidRule({}).check(forced) == []

    def test_a_repo_with_no_codex_catalog_still_reports(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / "plugins" / "one" / "commands").mkdir(parents=True)
        (repo / "plugins" / "one" / "commands" / "go.md").write_text("Go.\n", encoding="utf-8")
        found = messages(MarketplaceJsonValidRule({}).check(RepositoryContext(repo)))
        assert "Marketplace file not found" in found

    def test_an_excluded_catalog_does_not_exempt(self, tmp_path):
        repo = self._repo(tmp_path, "marketplace.json")
        context = RepositoryContext(repo, exclude_patterns=[".agents/plugins/**"])
        assert not context.codex_catalog_exists()

    def test_an_unrelated_sibling_does_not_exempt(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / "notes.json").write_text("{}", encoding="utf-8")
        assert not RepositoryContext(repo).codex_catalog_exists()
