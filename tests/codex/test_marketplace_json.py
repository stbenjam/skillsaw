"""``codex-marketplace-json-valid`` — catalog shape, sources, and policy."""

import json

import pytest

from skillsaw.docs.extractor import extract_docs
from skillsaw.docs.html_renderer import render_html
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formatters.json_fmt import format_json
from skillsaw.formatters.sarif import format_sarif
from skillsaw.rule import Severity
from skillsaw.rules.builtin.codex import (
    CodexMarketplaceJsonValidRule,
    CodexMarketplaceRegistrationRule,
    CodexPluginJsonValidRule,
)

from ._helpers import (
    copy_fixture,
    run_rule,
    messages,
    by_severity,
    _write_plugin,
    _codex_plugin_repo,
    _codex_marketplace_repo,
)


class TestMarketplaceJsonValid:
    @pytest.fixture
    def violations(self, tmp_path):
        return run_rule(CodexMarketplaceJsonValidRule, copy_fixture("codex/broken", tmp_path))

    def test_missing_name(self, violations):
        assert "Missing 'name' field" in messages(violations)

    def test_duplicate_entry_names(self, violations):
        assert any("duplicate plugin name" in m for m in messages(violations))

    def test_npm_source_requires_package(self, violations):
        assert any("requires a 'package' field" in m for m in messages(violations))

    def test_insecure_npm_registry(self, violations):
        registry = [m for m in messages(violations) if "registry" in m]
        assert len(registry) == 1
        assert "must use https" in registry[0]
        assert "must not embed credentials" in registry[0]
        assert "must not have a query string" in registry[0]

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_constants_are_invalid_json(self, tmp_path, literal):
        """Codex's strict parser rejects what Python's lenient reader accepts.

        Without this a catalog passes validity while the registration fixer
        refuses to reserialize it, so the two rules disagree about the same
        bytes.
        """
        repo = _codex_marketplace_repo(tmp_path, {"name": "numbers", "plugins": []})
        marketplace = repo / ".agents" / "plugins" / "marketplace.json"
        marketplace.write_text(
            '{"name":"numbers","interface":{"score":' + literal + '},"plugins":[]}\n',
            encoding="utf-8",
        )
        violations = run_rule(CodexMarketplaceJsonValidRule, repo)
        assert messages(violations) == [f"Invalid JSON: non-finite JSON number: {literal}"]

    def test_a_quoted_nan_inside_a_string_is_still_valid(self, tmp_path):
        """The substring prefilter only gates the strict reparse."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "nan-string",
                "interface": {"display_name": "NaN and Infinity dashboards"},
                "plugins": [],
            },
        )
        assert run_rule(CodexMarketplaceJsonValidRule, repo) == []

    def test_unparseable_npm_registry_is_reported_not_crashed(self, tmp_path):
        """``urlparse`` raises "Invalid IPv6 URL" on an unbalanced '['.

        Letting it escape aborts the whole rule, so the credential and
        scheme checks failed open on exactly the malformed input they exist
        to catch, and every other finding in every catalog was replaced by a
        rule-execution-error.
        """
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "bad-registry",
                "plugins": [
                    {
                        "name": "x",
                        "source": {
                            "source": "npm",
                            "package": "x",
                            "registry": "https://[oops",
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
        violations = run_rule(CodexMarketplaceJsonValidRule, repo)
        assert messages(violations) == ["plugins[0].source.registry is not a valid URL"]

    def test_registry_credentials_are_redacted_from_machine_reports(self, tmp_path):
        secret = "TOPSECRETTOKEN987"
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "credential-test",
                "plugins": [
                    {
                        "name": "x",
                        "source": {
                            "source": "npm",
                            "package": "x",
                            "registry": f"https://user:{secret}@registry.example.com",
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
        context = RepositoryContext(repo)
        rule = CodexMarketplaceJsonValidRule({})
        violations = rule.check(context)
        assert any("must not embed credentials" in v.message for v in violations)
        assert secret not in format_json(violations, context, [rule], "0.18.0")
        assert secret not in format_sarif(violations, context, [rule], "0.18.0")

    def test_empty_bare_string_source_is_an_error(self, tmp_path):
        """``""`` resolves to the marketplace root, so nothing else rejects it.

        The object form is caught by the required-field check; only the bare
        string branch degraded an unusable entry to an INFO about './'.
        """
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "empty-source",
                "plugins": [
                    {
                        "name": "x",
                        "source": "",
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        violations = run_rule(CodexMarketplaceJsonValidRule, repo)
        assert messages(violations) == ["plugins[0].source is an empty path"]
        assert violations[0].severity is Severity.ERROR

    def test_non_string_policy_values_config_does_not_crash(self, tmp_path):
        """``config_schema`` declares a bare list, so elements can be anything."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "x",
                        "source": {"source": "local", "path": "./plugins/x"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        violations = run_rule(CodexMarketplaceJsonValidRule, repo, {"installation-values": [1, 2]})
        assert any("known values: 1, 2" in m for m in messages(violations))

    def test_duplicate_name_still_reports_its_casing(self, tmp_path):
        """Both defects are real; returning early would hide the second."""
        entry = {
            "source": {"source": "local", "path": "./plugins/x"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {"name": "Bad_Name", **entry},
                    {"name": "Bad_Name", **entry},
                ],
            },
        )
        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert any("plugins[1] duplicate plugin name 'Bad_Name'" in m for m in found)
        assert any("plugins[1] plugin name 'Bad_Name' should use kebab-case" in m for m in found)

    def test_unrecognized_policy_values_warn(self, violations):
        warnings = messages(by_severity(violations, Severity.WARNING))
        assert any("policy.installation" in m and "MAYBE" in m for m in warnings)
        assert any("policy.authentication" in m and "ON_FIRST_USE" in m for m in warnings)

    def test_missing_category_warns(self, violations):
        assert any(
            "missing 'category'" in m for m in messages(by_severity(violations, Severity.WARNING))
        )

    def test_bare_string_source_without_prefix_is_info(self, violations):
        infos = messages(by_severity(violations, Severity.INFO))
        assert any("should start with './'" in m for m in infos)

    def test_policy_values_are_configurable(self, tmp_path):
        repo = copy_fixture("codex/broken", tmp_path)
        violations = run_rule(
            CodexMarketplaceJsonValidRule,
            repo,
            {
                "installation-values": ["AVAILABLE", "INSTALLED_BY_DEFAULT", "MAYBE"],
                "authentication-values": ["ON_INSTALL", "ON_FIRST_USE"],
            },
        )
        assert not any("unrecognized value" in m for m in messages(violations))

    def test_unknown_source_type_warns_rather_than_errors(self, tmp_path):
        """A source type added upstream must not break existing marketplaces."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "future",
                "plugins": [
                    {
                        "name": "tomorrow",
                        "source": {"source": "oci", "image": "example/plugin"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        violations = run_rule(CodexMarketplaceJsonValidRule, repo)
        assert by_severity(violations, Severity.ERROR) == []
        assert any("unknown source type 'oci'" in m for m in messages(violations))

    @pytest.mark.parametrize("source_type", ["", None, 42])
    def test_unusable_source_discriminator_is_an_error(self, tmp_path, source_type):
        """An empty discriminator is missing, not an unknown future type.

        Falling through to the forward-compatibility warning would let an
        entry Codex cannot resolve pass a default ``fail-on: error`` run.
        """
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "blank",
                "plugins": [
                    {
                        "name": "nowhere",
                        "source": {"source": source_type, "path": "./plugins/nowhere"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        errors = messages(
            by_severity(run_rule(CodexMarketplaceJsonValidRule, repo), Severity.ERROR)
        )
        assert any("missing required 'source' type field" in m for m in errors)

    def test_absolute_source_path_is_an_error(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "abs",
                "plugins": [
                    {
                        "name": "escapee",
                        "source": {"source": "local", "path": "/opt/plugins/escapee"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        errors = messages(
            by_severity(run_rule(CodexMarketplaceJsonValidRule, repo), Severity.ERROR)
        )
        assert any("absolute path" in m for m in errors)

    def test_non_string_local_path_is_reported(self, tmp_path):
        """Presence alone is not enough — a non-string path resolves to nothing."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "typed",
                "plugins": [
                    {
                        "name": "listy",
                        "source": {"source": "local", "path": ["./plugins/listy"]},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        violations = run_rule(CodexMarketplaceJsonValidRule, repo)
        assert any("source.path must be a non-empty string" in m for m in messages(violations))

    def test_explicit_null_policy_is_treated_as_missing(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "nulled",
                "plugins": [
                    {
                        "name": "a",
                        "source": "./plugins/a",
                        "policy": None,
                        "category": None,
                    },
                    {
                        "name": "b",
                        "source": "./plugins/b",
                        "policy": {"installation": None, "authentication": None},
                        "category": "Productivity",
                    },
                ],
            },
        )
        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert any("plugins[0] missing 'policy'" in m for m in found)
        assert any("plugins[0] missing 'category'" in m for m in found)
        assert any("plugins[1].policy missing 'installation'" in m for m in found)
        assert any("plugins[1].policy missing 'authentication'" in m for m in found)

    def test_invalid_json_reports_once(self, tmp_path):
        repo = _codex_marketplace_repo(tmp_path, {"name": "x", "plugins": []})
        (repo / ".agents" / "plugins" / "marketplace.json").write_text("{", encoding="utf-8")
        violations = run_rule(CodexMarketplaceJsonValidRule, repo)
        assert len(violations) == 1
        assert violations[0].message.startswith("Invalid JSON")


class TestRegistryHostname:
    @pytest.mark.parametrize(
        "registry",
        ["https:registry.example.com", "https:///registry", "https://"],
    )
    def test_hostless_registry_is_rejected(self, tmp_path, registry):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "pkg",
                        "source": {
                            "source": "npm",
                            "package": "@x/y",
                            "registry": registry,
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert any("must name a host" in m for m in found)

    def test_a_real_registry_still_passes(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "pkg",
                        "source": {
                            "source": "npm",
                            "package": "@x/y",
                            "registry": "https://registry.example.com",
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        assert run_rule(CodexMarketplaceJsonValidRule, repo) == []


class TestCategoryShape:
    @pytest.mark.parametrize("category", ["", 42, [], {}])
    def test_malformed_category_is_reported(self, tmp_path, category):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "pkg",
                        "source": {"source": "url", "url": "https://example.com/x.git"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": category,
                    }
                ],
            },
        )
        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert any("'category' must be a non-empty string" in m for m in found)


class TestConfigAndUrlEdgeCases:
    def test_a_non_string_recommended_field_does_not_crash_the_rule(self, tmp_path):
        repo = _codex_plugin_repo(tmp_path, {"name": "cfg", "version": "1.0.0", "description": "x"})
        violations = run_rule(
            CodexPluginJsonValidRule, repo, {"recommended-fields": [[], "version"]}
        )
        assert violations == []

    @pytest.mark.parametrize(
        "registry", ["https://r.example.com:not-a-port", "https://r.example.com:99999"]
    )
    def test_an_invalid_port_is_reported(self, tmp_path, registry):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "pkg",
                        "source": {
                            "source": "npm",
                            "package": "@x/y",
                            "registry": registry,
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert any("invalid port" in m for m in found)

    def test_a_valid_port_still_passes(self, tmp_path):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "pkg",
                        "source": {
                            "source": "npm",
                            "package": "@x/y",
                            "registry": "https://r.example.com:8443",
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_USE",
                        },
                        "category": "Productivity",
                    }
                ],
            },
        )
        assert run_rule(CodexMarketplaceJsonValidRule, repo) == []


class TestPolicyConfigRobustness:
    @pytest.mark.parametrize("bad", [None, 42, "AVAILABLE"])
    def test_a_non_iterable_value_set_does_not_crash_the_rule(self, tmp_path, bad):
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "cat",
                "plugins": [
                    {
                        "name": "pkg",
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
        # must not raise
        run_rule(CodexMarketplaceJsonValidRule, repo, {"installation-values": bad})


class TestMalformedCatalogShapes:
    """Every branch that gives up on a catalog document, not just the one
    the fixture happens to exercise."""

    @pytest.mark.parametrize(
        "body",
        [
            "{ not json",
            '["a", "b"]',
            '"just a string"',
            '{"name": "cat"}',
            '{"name": "cat", "plugins": "not-a-list"}',
            '{"name": "cat", "plugins": [42, null, "x"]}',
        ],
    )
    def test_a_malformed_catalog_produces_violations_not_a_crash(self, tmp_path, body):
        repo = tmp_path / "repo"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / "marketplace.json").write_text(body, encoding="utf-8")

        for rule in (CodexMarketplaceJsonValidRule, CodexMarketplaceRegistrationRule):
            run_rule(rule, repo)  # must not raise


class TestMalformedMarketplaceEntrypoint:
    def test_a_directory_in_place_of_the_catalog_is_reported(self, tmp_path):
        repo = tmp_path / "dir-catalog"
        (repo / ".agents" / "plugins" / "marketplace.json").mkdir(parents=True)

        context = RepositoryContext(repo)
        assert RepositoryType.CODEX_MARKETPLACE in context.repo_types

        found = messages(CodexMarketplaceJsonValidRule({}).check(context))
        assert found, "the unusable entrypoint was reported by nothing"


class TestMalformedSiblingCatalog:
    def test_a_catalog_named_sibling_is_kept_when_its_json_is_broken(self, tmp_path):
        repo = copy_fixture("codex/clean", tmp_path)
        broken = repo / ".agents" / "plugins" / "api_marketplace.json"
        broken.write_text('{"name": "api", "plugins": [', encoding="utf-8")

        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert any(m.startswith("Invalid JSON:") for m in found)

    def test_a_catalog_named_sibling_is_kept_when_plugins_is_not_a_list(self, tmp_path):
        repo = copy_fixture("codex/clean", tmp_path)
        (repo / ".agents" / "plugins" / "api_marketplace.json").write_text(
            json.dumps({"name": "api", "plugins": {}}), encoding="utf-8"
        )

        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert "'plugins' must be an array" in found

    def test_it_alone_enables_codex_marketplace_detection(self, tmp_path):
        """Without this the only catalog in the repo would be invisible."""
        repo = tmp_path / "sibling-only"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        (repo / ".agents" / "plugins" / "api_marketplace.json").write_text(
            "{ not json", encoding="utf-8"
        )

        assert RepositoryType.CODEX_MARKETPLACE in RepositoryContext(repo).repo_types


class TestSourceIdentity:
    def test_equivalent_source_spellings_are_not_duplicates(self, tmp_path):
        """`./plugins/foo` and the object form install the same directory."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "primary",
                "plugins": [
                    {
                        "name": "shared",
                        "source": "./plugins/one",
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
                            "source": {"source": "local", "path": "plugins/one"},
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

        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert not any("duplicate plugin name" in m for m in found)


class TestSourceNormalizationPrecision:
    def test_a_hidden_directory_is_not_confused_with_a_visible_one(self, tmp_path):
        """`lstrip("./")` would eat the dot, making ./.plugins/foo == ./plugins/foo."""
        repo = _codex_marketplace_repo(
            tmp_path,
            {
                "name": "primary",
                "plugins": [
                    {
                        "name": "shared",
                        "source": {"source": "local", "path": "./.plugins/foo"},
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
                            "source": {"source": "local", "path": "./plugins/foo"},
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
        found = messages(run_rule(CodexMarketplaceJsonValidRule, repo))
        assert any("duplicate plugin name 'shared'" in m for m in found)


class TestUnhashableSourceDiscriminator:
    @pytest.mark.parametrize("bad", [[], {}, 42])
    def test_a_non_string_discriminator_does_not_raise(self, tmp_path, bad):
        repo = _codex_marketplace_repo(
            tmp_path,
            {"name": "cat", "plugins": [{"name": "x", "source": {"source": bad}}]},
        )
        run_rule(CodexMarketplaceRegistrationRule, repo)  # must not raise
        assert render_html(extract_docs(RepositoryContext(repo)))
