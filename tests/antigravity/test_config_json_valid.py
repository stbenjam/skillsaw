"""``antigravity-config-json-valid``: the registry files, opt-in."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillsaw.formats.antigravity import REGISTRY_FILENAMES
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.antigravity.config_json_valid import AntigravityConfigJsonValidRule

from ._helpers import messages, only, run_rule, write_customization, write_repo


def check(tmp_path: Path, name: str, body: str, filename: str = "agents.json"):
    repo = write_repo(tmp_path / name)
    write_customization(repo, filename, body)
    return run_rule(AntigravityConfigJsonValidRule, repo)


class TestAcceptedRegistries:
    @pytest.mark.parametrize(
        "name,body",
        [
            ("empty", "{}"),
            ("null-root", "null"),
            ("null-entry", '{"entries": [null]}'),
            ("missing-path", '{"entries": [{}]}'),
            ("plural-key", '{"entries": [{"paths": ["a"]}]}'),
            ("null-path", '{"entries": [{"path": null}]}'),
            ("ignored-overflow", '{"entries": [], "weight": 1e400}'),
            ("entries", '{"entries": [{"path": "internal/schedule/agents"}]}'),
            ("filters", '{"entries": [{"path": "a", "include_only": ["x-*"], "exclude": ["y"]}]}'),
            ("inherits", '{"entries": [], "inherits": [{"path": "~/.gemini/config"}]}'),
            # Unknown keys are ignored by ``encoding/json``, and unverified
            # keys are not this rule's business.
            ("unknown-key", '{"entries": [], "flavour": "vanilla"}'),
            # Go decodes ``null`` as the zero value, so each of these reads
            # as the key being absent rather than as a malformed registry.
            ("null-entries", '{"entries": null}'),
            ("null-inherits", '{"entries": [], "inherits": null}'),
        ],
    )
    def test_no_findings(self, tmp_path: Path, name: str, body: str) -> None:
        assert messages(check(tmp_path, name, body)) == []

    @pytest.mark.parametrize(
        "name,body",
        [
            (
                "entries",
                '{"entries": [{"path": "tools/one"}], "entries": [{"path": "tools/two"}]}',
            ),
            ("path", '{"entries": [{"path": "tools/one", "path": "tools/two"}]}'),
        ],
    )
    def test_repeated_event_key_is_last_wins(self, tmp_path: Path, name: str, body: str) -> None:
        """Measured against a functional registry: the last path's directory loads."""
        assert messages(check(tmp_path, f"dup-{name}", body)) == []


class TestSkippedRegistries:
    @pytest.mark.parametrize(
        "name,body,needle",
        [
            ("unparseable", '{"entries": }', "does not parse"),
            ("bom", '\ufeff{"entries": []}', "UTF-8 BOM"),
            ("array-root", "[1, 2]", "must be a JSON object"),
            ("non-finite", '{"entries": [], "weight": NaN}', "not valid JSON"),
        ],
    )
    def test_file_is_skipped(self, tmp_path: Path, name: str, body: str, needle: str) -> None:
        found = only(check(tmp_path, name, body), needle)
        assert "loads nothing from this registry" in found.message
        assert found.severity == Severity.ERROR


class TestEntryShape:
    def test_entries_must_be_an_array(self, tmp_path: Path) -> None:
        only(check(tmp_path, "entries-object", '{"entries": {"path": "a"}}'), "must be an array")

    @pytest.mark.parametrize(
        "name,body",
        (
            ("bare-string", '{"entries": ["internal/schedule/agents"]}'),
            ("number-path", '{"entries": [{"path": 5}]}'),
        ),
    )
    def test_entry_must_carry_a_string_path(self, tmp_path: Path, name: str, body: str) -> None:
        found = only(check(tmp_path, f"entry-{name}", body), "entries[0]")
        assert "string 'path'" in found.message
        assert found.severity == Severity.ERROR

    def test_one_finding_names_several_positions(self, tmp_path: Path) -> None:
        body = '{"entries": [1, 2, 3, 4, 5]}'
        violations = check(tmp_path, "many-bad", body)
        assert len(violations) == 1
        assert "entries[0], entries[1], entries[2] and 2 more" in violations[0].message


class TestEveryRegistryFilename:
    @pytest.mark.parametrize("filename", REGISTRY_FILENAMES)
    def test_each_registry_is_read(self, tmp_path: Path, filename: str) -> None:
        violations = check(tmp_path, filename.replace(".", "-"), "[]", filename)
        assert len(violations) == 1
        assert violations[0].file_path.name == filename

    def test_rules_json_is_not_a_registry(self, tmp_path: Path) -> None:
        """A literal in the binary with no loader reached for it."""
        assert "rules.json" not in REGISTRY_FILENAMES
        assert check(tmp_path, "rules-json", "[]", "rules.json") == []


class TestGating:
    def test_rule_is_opt_in(self) -> None:
        assert AntigravityConfigJsonValidRule.default_enabled is False
        assert AntigravityConfigJsonValidRule.since == "0.20.0"

    def test_repo_types(self) -> None:
        assert AntigravityConfigJsonValidRule.repo_types == frozenset(
            {RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN}
        )

    def test_default_run_reports_nothing(self, tmp_path: Path) -> None:
        from tests.test_integration import run_lint

        repo = write_repo(tmp_path / "default-off")
        write_customization(repo, "agents.json", "[]")
        report = run_lint(repo)["out"] or {}
        assert [
            v
            for v in report.get("violations", [])
            if v["rule_id"] == "antigravity-config-json-valid"
        ] == []
