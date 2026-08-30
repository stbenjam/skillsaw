"""Conformance tests for ``agent-plugin-json-valid``."""

import json

import pytest

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Severity

from ._helpers import PLUGIN_JSON_RULE, copy_fixture, lint_rules, messages_lower

SCHEMA_BASE = "https://agent-plugins.org/schemas/1.0.0"

SKILL_BODY = """---
name: release-audit
description: Audit a release branch before publishing it to the registry.
---

# Release audit

Check the changelog, the version bump, and the signed tag.
"""


def _write_manifest(root, **fields):
    """Write a plugin.json whose canonical fields can be overridden."""
    manifest = {"$schema": f"{SCHEMA_BASE}/plugin.schema.json", "name": "fixture-plugin"}
    manifest.update(fields)
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _finding_for(findings, needle: str):
    return [item for item in findings if needle in item.message.lower()]


def _has_location_finding(findings, needle: str) -> bool:
    location_words = ("outside", "within", "contain")
    messages = messages_lower(findings)
    return any(
        needle in message and any(word in message for word in location_words)
        for message in messages
    )


class TestManifestSchema:
    def test_clean_full_manifest_passes(self, tmp_path):
        repo = copy_fixture("agent-plugins/clean", tmp_path)
        assert lint_rules(repo, PLUGIN_JSON_RULE) == []

    def test_recommended_metadata_formats_are_not_rejected(self, tmp_path):
        repo = copy_fixture("agent-plugins/metadata-lax", tmp_path)
        assert lint_rules(repo, PLUGIN_JSON_RULE) == []

    @pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
    def test_supported_schema_versions_pass(self, tmp_path, version):
        manifest = {
            "$schema": f"https://agent-plugins.org/schemas/{version}/plugin.schema.json",
            "name": "versioned-plugin",
            "extensions": {"com.example.client": {"enabled": True}},
        }
        (tmp_path / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

        assert lint_rules(tmp_path, PLUGIN_JSON_RULE) == []

    def test_schema_types_and_name_constraints_are_reported(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-manifest", tmp_path)
        findings = lint_rules(repo, PLUGIN_JSON_RULE)
        combined = "\n".join(messages_lower(findings))

        assert "does not conform" in combined
        assert "schema error" in combined
        assert any(finding.severity is Severity.ERROR for finding in findings)
        expected_path = repo / "plugin.json"
        assert all(item.file_path == expected_path for item in findings)

    @pytest.mark.parametrize(
        ("field", "invalid_value"),
        [
            ("name", "Bad--Plugin"),
            ("version", 18),
            ("description", False),
            ("author", {"email": 42}),
            ("keywords", "release"),
        ],
    )
    def test_each_manifest_constraint_names_the_invalid_field(
        self,
        tmp_path,
        field,
        invalid_value,
    ):
        schema_url = "/".join(
            (
                "https://agent-plugins.org/schemas/1.0.0",
                "plugin.schema.json",
            )
        )
        manifest = {
            "$schema": schema_url,
            "name": "valid-plugin",
            field: invalid_value,
        }
        (tmp_path / "plugin.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

        findings = lint_rules(tmp_path, PLUGIN_JSON_RULE)

        assert findings
        assert any(field in message for message in messages_lower(findings))

    def test_malformed_json_is_reported(self, tmp_path):
        repo = copy_fixture("agent-plugins/malformed-manifest", tmp_path)
        findings = lint_rules(repo, PLUGIN_JSON_RULE)

        assert len(findings) == 1
        assert "json" in findings[0].message.lower()

    def test_duplicate_json_object_key_is_reported(self, tmp_path):
        (tmp_path / "plugin.json").write_text(
            '{"name": "first", "name": "second"}',
            encoding="utf-8",
        )

        findings = lint_rules(
            tmp_path,
            PLUGIN_JSON_RULE,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )

        assert len(findings) == 1
        assert "duplicate json object key" in findings[0].message.lower()

    def test_unsupported_canonical_schema_version_is_reported(self, tmp_path):
        repo = copy_fixture("agent-plugins/unsupported-schema", tmp_path)
        findings = lint_rules(repo, PLUGIN_JSON_RULE)

        assert findings
        combined = "\n".join(messages_lower(findings))
        assert "schema" in combined
        assert "unsupported" in combined
        assert "1.0.0" in combined and "1.1.0" in combined

    def test_unknown_fields_are_warnings_not_plugin_fatal(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-manifest", tmp_path)
        findings = lint_rules(repo, PLUGIN_JSON_RULE)

        unknown = _finding_for(findings, "components")
        assert unknown
        assert all(finding.severity is Severity.WARNING for finding in unknown)

    def test_non_object_extensions_is_a_warning(self, tmp_path):
        repo = copy_fixture("agent-plugins/broken-manifest", tmp_path)
        findings = lint_rules(repo, PLUGIN_JSON_RULE)

        extensions = _finding_for(findings, "extensions")
        assert extensions
        assert {item.severity for item in extensions} == {Severity.WARNING}

    def test_unknown_extension_namespace_object_contents_are_opaque(self, tmp_path):
        manifest = {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "opaque-extension-data",
            "extensions": {
                "com.example.unimplemented": {
                    "client-defined": [True, {"nested": "anything"}],
                },
            },
        }
        (tmp_path / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

        assert lint_rules(tmp_path, PLUGIN_JSON_RULE) == []

    def test_extension_namespace_value_must_be_an_object(self, tmp_path):
        manifest = {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "invalid-extension-value",
            "extensions": {
                "com.example.unimplemented": "not an object",
            },
        }
        (tmp_path / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

        findings = lint_rules(tmp_path, PLUGIN_JSON_RULE)

        assert findings
        assert any(item.severity is Severity.ERROR for item in findings)
        assert _finding_for(findings, "extensions")


class TestFixedLocationsAndContainment:
    def test_skills_must_be_a_directory_when_present(self, tmp_path):
        repo = copy_fixture("agent-plugins/wrong-kinds", tmp_path)
        findings = lint_rules(repo, PLUGIN_JSON_RULE)

        combined = "\n".join(messages_lower(findings))
        assert "skills" in combined
        assert "directory" in combined or "folder" in combined

    def test_escaping_skills_symlink_is_not_discovered(self, tmp_path):
        fixture = copy_fixture("agent-plugins/containment", tmp_path)
        repo = fixture / "repo"
        assert (repo / "skills").is_symlink()

        findings = lint_rules(repo, PLUGIN_JSON_RULE)
        context = RepositoryContext(repo)

        assert _has_location_finding(findings, "skills")
        assert context.skills == []

    def test_escaping_entry_does_not_hide_valid_siblings(self, tmp_path):
        fixture = copy_fixture("agent-plugins/skill-entry-escape", tmp_path)
        repo = fixture / "repo"
        assert (repo / "skills" / "escaping" / "SKILL.md").is_symlink()

        findings = lint_rules(repo, PLUGIN_JSON_RULE)
        context = RepositoryContext(repo)

        assert _has_location_finding(findings, "skill")
        assert [path.name for path in context.skills] == ["valid"]

    def test_missing_optional_component_locations_are_clean(self, tmp_path):
        repo = copy_fixture("agent-plugins/metadata-lax", tmp_path)
        assert lint_rules(repo, PLUGIN_JSON_RULE) == []

    def test_manifest_directory_is_not_a_manifest(self, tmp_path):
        (tmp_path / "plugin.json").mkdir()

        findings = lint_rules(
            tmp_path,
            PLUGIN_JSON_RULE,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )

        assert any(
            "plugin.json" in message and "regular file" in message
            for message in messages_lower(findings)
        ), messages_lower(findings)

    def test_escaping_skill_directory_does_not_hide_valid_siblings(self, tmp_path):
        outside = tmp_path / "outside" / "borrowed"
        (outside / "nested").mkdir(parents=True)
        repo = tmp_path / "repo"
        skills = repo / "skills"
        (skills / "valid").mkdir(parents=True)
        (skills / "valid" / "SKILL.md").write_text(SKILL_BODY, encoding="utf-8")
        (skills / "escaping").symlink_to("../../outside/borrowed", target_is_directory=True)
        _write_manifest(repo)

        findings = lint_rules(repo, PLUGIN_JSON_RULE)
        context = RepositoryContext(repo)

        assert any(
            "escaping" in message and "outside the plugin root" in message
            for message in messages_lower(findings)
        ), messages_lower(findings)
        assert all("valid" not in message for message in messages_lower(findings))
        assert [path.name for path in context.skills] == ["valid"]

    def test_skill_entrypoint_directory_is_not_an_entrypoint(self, tmp_path):
        repo = tmp_path / "repo"
        skills = repo / "skills"
        (skills / "shaped-like-a-skill" / "SKILL.md").mkdir(parents=True)
        (skills / "valid").mkdir()
        (skills / "valid" / "SKILL.md").write_text(SKILL_BODY, encoding="utf-8")
        _write_manifest(repo)

        findings = lint_rules(repo, PLUGIN_JSON_RULE)

        assert any(
            "shaped-like-a-skill/skill.md" in message and "regular file" in message
            for message in messages_lower(findings)
        ), messages_lower(findings)
        assert all("valid/skill.md" not in message for message in messages_lower(findings))

    def test_non_canonical_manifest_schema_identifier_is_reported(self, tmp_path):
        _write_manifest(tmp_path, **{"$schema": "https://example.com/plugin.json"})

        findings = lint_rules(
            tmp_path,
            PLUGIN_JSON_RULE,
            repo_types={RepositoryType.AGENT_PLUGIN},
        )

        assert any("canonical" in message for message in messages_lower(findings)), messages_lower(
            findings
        )


def test_manifest_rule_is_scoped_to_agent_plugin_repositories(tmp_path):
    repo = copy_fixture("agent-plugins/legacy-root", tmp_path)
    assert lint_rules(repo, PLUGIN_JSON_RULE) == []
