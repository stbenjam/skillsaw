"""``antigravity-mcp-valid``: startup-fatal files, silently dropped servers."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.antigravity.mcp_valid import AntigravityMcpValidRule
from skillsaw.rules.builtin.mcp.valid_json import McpValidJsonRule

from ._helpers import messages, only, repo_with_mcp, run_rule, write_plugin, write_repo

WORKING = '{"mcpServers": {"gtfs": {"serverUrl": "https://feeds.example/mcp"}}}'


def check(tmp_path: Path, name: str, body: str, dirname: str = ".agents"):
    repo = repo_with_mcp(tmp_path, name, body, dirname)
    return run_rule(AntigravityMcpValidRule, repo)


class TestAcceptedFiles:
    """Shapes ``agy`` loads, which an ERROR rule must not touch."""

    @pytest.mark.parametrize(
        "name,body",
        [
            ("remote", WORKING),
            ("empty", '{"mcpServers": {}}'),
            ("stdio", '{"mcpServers": {"db": {"command": "./bin/db", "args": ["--ro"]}}}'),
            ("env-strings", '{"mcpServers": {"db": {"command": "x", "env": {"K": "v"}}}}'),
            ("env-null", '{"mcpServers": {"db": {"command": "x", "env": null}}}'),
            ("cwd", '{"mcpServers": {"db": {"command": "x", "cwd": "/srv"}}}'),
            # ``serverUrl`` wins over ``command``; both present is not a defect.
            ("both", '{"mcpServers": {"db": {"command": "x", "serverUrl": "https://e.example"}}}'),
            # ``url`` plus ``type`` is a third accepted shape.
            ("url-type", '{"mcpServers": {"t": {"type": "http", "url": "https://e.example"}}}'),
            ("url-alone", '{"mcpServers": {"t": {"url": "https://e.example"}}}'),
            # A server with no connection field at all loads without complaint.
            ("no-connection", '{"mcpServers": {"t": {}}}'),
            ("disabled", '{"mcpServers": {"t": {"command": "x", "disabled": true}}}'),
            # ``enabled`` is not a key ``agy`` reads, and unknown keys are tolerated.
            ("enabled-key", '{"mcpServers": {"t": {"command": "x", "enabled": false}}}'),
            ("unknown-key", '{"mcpServers": {"t": {"command": "x", "flavour": "vanilla"}}}'),
            ("disabled-tools", '{"mcpServers": {"t": {"command": "x", "disabledTools": ["a"]}}}'),
            (
                "auth-provider",
                '{"mcpServers": {"t": {"url": "https://e.example",'
                ' "authProviderType": "google_credentials"}}}',
            ),
            ("oauth-empty", '{"mcpServers": {"t": {"url": "https://e.example", "oauth": {}}}}'),
            # Measured with ``agy mcp list``: a null field is the key's
            # absence and the server still loads.
            ("null-server-url", '{"mcpServers": {"t": {"command": "x", "serverUrl": null}}}'),
        ],
    )
    def test_no_findings(self, tmp_path: Path, name: str, body: str) -> None:
        assert messages(check(tmp_path, name, body)) == []

    @pytest.mark.parametrize(
        "name,body",
        [
            (
                "wrapper",
                '{"mcpServers": {"a": {"command": "x"}}, "mcpServers": {"b": {"command": "y"}}}',
            ),
            (
                "server-name",
                '{"mcpServers": {"s": {"command": "x"}, "s": {"command": "y"}}}',
            ),
            (
                "server-key",
                '{"mcpServers": {"s": {"command": "x", "command": "y"}}}',
            ),
        ],
    )
    def test_repeated_event_key_is_last_wins(self, tmp_path: Path, name: str, body: str) -> None:
        """``agy mcp list`` shows the last value at all three depths, no diagnostic."""
        assert messages(check(tmp_path, f"dup-{name}", body)) == []


class TestStartupFatal:
    """Exit 1, and no session starts."""

    @pytest.mark.parametrize(
        "name,body,needle",
        [
            ("bad-json", '{"mcpServers": }', "Invalid JSON"),
            ("trailing-comma", '{"mcpServers": {"t": {"command": "x",}}}', "Invalid JSON"),
            ("comment", '{"mcpServers": {} /* none yet */}', "Invalid JSON"),
            ("array-root", "[]", "must be a JSON object"),
            ("non-finite", '{"mcpServers": {"t": {"timeout": 1e400}}}', "not valid JSON"),
        ],
    )
    def test_reported_at_error(self, tmp_path: Path, name: str, body: str, needle: str) -> None:
        found = only(check(tmp_path, name, body), needle)
        assert found.severity == Severity.ERROR
        assert "exits 1" in found.message


class TestInertFile:
    """A document with no wrapper loads nothing, and is not an error."""

    def test_bare_server_map(self, tmp_path: Path) -> None:
        found = only(
            check(tmp_path, "bare", '{"db": {"command": "./bin/db"}}'), "no 'mcpServers' object"
        )
        assert found.severity == Severity.WARNING

    def test_empty_document(self, tmp_path: Path) -> None:
        found = only(check(tmp_path, "empty-doc", "{}"), "no 'mcpServers' object")
        assert found.severity == Severity.WARNING


class TestDroppedServers:
    """A per-server shape problem drops that server, silently."""

    @pytest.mark.parametrize(
        "name,body,needle",
        [
            (
                "server-not-object",
                '{"mcpServers": {"t": "https://e.example"}}',
                "must be a JSON object",
            ),
            (
                "env-value",
                '{"mcpServers": {"t": {"command": "x", "env": {"PORT": 5432}}}}',
                "every 'env' value must be a string",
            ),
            (
                "env-not-object",
                '{"mcpServers": {"t": {"command": "x", "env": ["PORT=5432"]}}}',
                "'env' must be an object",
            ),
            (
                "args-element",
                '{"mcpServers": {"t": {"command": "x", "args": ["--ro", 5]}}}',
                "every 'args' element must be a string",
            ),
            (
                "args-not-array",
                '{"mcpServers": {"t": {"command": "x", "args": "--ro"}}}',
                "'args' must be an array",
            ),
            (
                "server-url-type",
                '{"mcpServers": {"t": {"serverUrl": ["https://e.example"]}}}',
                "'serverUrl' must be a string",
            ),
            (
                "disabled-tools-type",
                '{"mcpServers": {"t": {"command": "x", "disabledTools": "a"}}}',
                "'disabledTools' must be an array of strings",
            ),
            (
                "auth-provider-alias",
                '{"mcpServers": {"t": {"url": "https://e.example", "authProviderType": "oauth"}}}',
                "'authProviderType' must be 'google_credentials'",
            ),
            (
                "auth-provider-enum",
                '{"mcpServers": {"t": {"url": "https://e.example",'
                ' "authProviderType": "MCP_AUTH_PROVIDER_TYPE_GOOGLE_CREDENTIALS"}}}',
                "'authProviderType' must be 'google_credentials'",
            ),
            # An array and an object are unhashable, so a membership test
            # that reaches them raises instead of reporting. Measured: ``agy``
            # drops the server for either, exactly as for an unknown string.
            (
                "auth-provider-array",
                '{"mcpServers": {"t": {"url": "https://e.example",'
                ' "authProviderType": ["google_credentials"]}}}',
                "'authProviderType' must be 'google_credentials'",
            ),
            (
                "auth-provider-object",
                '{"mcpServers": {"t": {"url": "https://e.example",'
                ' "authProviderType": {"type": "google_credentials"}}}}',
                "'authProviderType' must be 'google_credentials'",
            ),
        ],
    )
    def test_reported_at_warning(self, tmp_path: Path, name: str, body: str, needle: str) -> None:
        found = only(check(tmp_path, name, body), needle)
        assert found.severity == Severity.WARNING
        assert "drops the server silently" in found.message

    def test_siblings_are_unaffected(self, tmp_path: Path) -> None:
        violations = check(
            tmp_path,
            "siblings",
            '{"mcpServers": {"good": {"command": "x"}, "bad": {"command": "y", "args": 5}}}',
        )
        assert len(violations) == 1
        assert "'bad'" in violations[0].message


class TestSharedRuleStandsDown:
    """``mcp-valid-json`` defers the shape and keeps what the dialect cannot change."""

    def test_shape_checks_are_not_duplicated(self, tmp_path: Path) -> None:
        repo = repo_with_mcp(tmp_path, "deferred", WORKING)
        assert messages(run_rule(McpValidJsonRule, repo)) == []

    def test_credentials_in_oauth_are_still_scanned(self, tmp_path: Path) -> None:
        secret = "sk-live-" + "9f2c41a8" + "b7de4c6390af"  # assembled: no literal token in the tree
        body = (
            '{"mcpServers": {"t": {"url": "https://e.example", "oauth":'
            f' {{"clientId": "ferrymark", "clientSecret": "{secret}"}}}}}}}}'
        )
        repo = repo_with_mcp(tmp_path, "oauth-secret", body)
        assert any("clientSecret" in m for m in messages(run_rule(McpValidJsonRule, repo)))

    def test_credentials_in_a_server_level_field_are_scanned(self, tmp_path: Path) -> None:
        """``clientSecret`` loads as a scalar on the server, not only in ``oauth``."""
        secret = "sk-live-" + "9f2c41a8" + "b7de4c6390af"  # assembled: no literal token in the tree
        body = (
            '{"mcpServers": {"t": {"url": "https://e.example",'
            f' "clientId": "ferrymark", "clientSecret": "{secret}"}}}}}}'
        )
        repo = repo_with_mcp(tmp_path, "field-secret", body)
        found = only(run_rule(McpValidJsonRule, repo), "clientSecret")
        assert "credential-bearing server field" in found.message
        assert secret not in found.message

    def test_a_placeholder_server_level_field_is_not_a_finding(self, tmp_path: Path) -> None:
        body = (
            '{"mcpServers": {"t": {"url": "https://e.example",'
            ' "clientId": "ferrymark", "clientSecret": "${ANTIGRAVITY_CLIENT_SECRET}"}}}'
        )
        repo = repo_with_mcp(tmp_path, "field-placeholder", body)
        assert messages(run_rule(McpValidJsonRule, repo)) == []

    def test_credentials_in_headers_are_still_scanned(self, tmp_path: Path) -> None:
        body = (
            '{"mcpServers": {"t": {"serverUrl": "https://e.example", "headers":'
            f' {{"Authorization": "Bearer {"sk-live-" + "9f2c41a8" + "b7de4c6390af"}"}}}}}}}}'
        )
        repo = repo_with_mcp(tmp_path, "header-secret", body)
        assert any("Authorization" in m for m in messages(run_rule(McpValidJsonRule, repo)))

    def test_server_url_user_information_is_still_scanned(self, tmp_path: Path) -> None:
        """``serverUrl`` is this host's spelling of the field the shared check reads."""
        body = '{"mcpServers": {"t": {"serverUrl": "https://ferry:hunter2@e.example/mcp"}}}'
        repo = repo_with_mcp(tmp_path, "userinfo", body)
        assert any("user information" in m for m in messages(run_rule(McpValidJsonRule, repo)))

    def test_owner_reports_the_syntax_error_alone(self, tmp_path: Path) -> None:
        """One defect, one finding: the shared rule leaves it to this one."""
        from tests.test_integration import run_lint

        repo = repo_with_mcp(tmp_path, "one-finding", '{"mcpServers": }')
        report = run_lint(repo)["out"] or {}
        reporting = [v["rule_id"] for v in report.get("violations", [])]
        assert reporting == ["antigravity-mcp-valid"]

    def test_disabling_the_owner_rule_keeps_the_credential_scan(self, tmp_path: Path) -> None:
        """Gating off a shape rule is not a request to stop scanning for a secret.

        Driven through the linter rather than the rule, because the gate
        lives in the surface set the linter builds; a direct ``check()``
        leaves it unset and never reaches the branch.
        """
        from tests.test_integration import run_lint

        secret = "sk-live-" + "9f2c41a8" + "b7de4c6390af"  # assembled: no literal token in the tree
        body = (
            '{"mcpServers": {"t": {"url": "https://e.example", "oauth":'
            f' {{"clientId": "ferrymark", "clientSecret": "{secret}"}}}}}}}}'
        )
        repo = repo_with_mcp(tmp_path, "owner-disabled", body)
        (repo / ".skillsaw.yaml").write_text(
            "rules:\n  antigravity-mcp-valid:\n    enabled: false\n", encoding="utf-8"
        )
        found = (run_lint(repo)["out"] or {}).get("violations", [])
        assert [v["rule_id"] for v in found] == ["mcp-valid-json"]
        assert "clientSecret" in found[0]["message"]
        assert secret not in found[0]["message"]

    def test_a_gated_off_owner_keeps_the_server_inventory(self, tmp_path: Path) -> None:
        """``mcp-prohibited`` is policy: the server is in the repository either way."""
        from skillsaw.rules.builtin.mcp.prohibited import McpProhibitedRule

        repo = repo_with_mcp(tmp_path, "owner-disabled-inventory", WORKING)
        rule = McpProhibitedRule({"allowlist": []})
        rule._enabled_surface_rule_ids = frozenset()
        found = rule.check(RepositoryContext(repo))
        assert any("gtfs" in m or "mcp_config.json" in m for m in messages(found))

    def test_a_gated_off_owner_leaves_the_shape_unreported(self, tmp_path: Path) -> None:
        """The shape walk stays down: the Claude reading calls this dialect broken."""
        from tests.test_integration import run_lint

        repo = repo_with_mcp(tmp_path, "owner-disabled-shape", WORKING)
        (repo / ".skillsaw.yaml").write_text(
            "rules:\n  antigravity-mcp-valid:\n    enabled: false\n", encoding="utf-8"
        )
        result = run_lint(repo)
        assert result["rc"] == 0
        assert (result["out"] or {}).get("violations", []) == []


class TestExtraAuthProviderTypes:
    """The escape hatch for a provider newer than this release."""

    def _check(self, tmp_path: Path, name: str, body: str, config):
        repo = repo_with_mcp(tmp_path, name, body)
        return run_rule(AntigravityMcpValidRule, repo, config)

    def test_declared_provider_is_accepted(self, tmp_path: Path) -> None:
        body = (
            '{"mcpServers": {"t": {"url": "https://e.example",'
            ' "authProviderType": "workspace_credentials"}}}'
        )
        config = {"extra-auth-provider-types": ["workspace_credentials"]}
        assert messages(self._check(tmp_path, "extra-auth", body, config)) == []

    def test_the_measured_provider_still_passes(self, tmp_path: Path) -> None:
        body = (
            '{"mcpServers": {"t": {"url": "https://e.example",'
            ' "authProviderType": "google_credentials"}}}'
        )
        config = {"extra-auth-provider-types": ["workspace_credentials"]}
        assert messages(self._check(tmp_path, "extra-auth-both", body, config)) == []

    def test_an_undeclared_provider_is_still_reported(self, tmp_path: Path) -> None:
        body = '{"mcpServers": {"t": {"url": "https://e.example", "authProviderType": "oauth"}}}'
        config = {"extra-auth-provider-types": ["workspace_credentials"]}
        found = only(
            self._check(tmp_path, "extra-auth-other", body, config), "'authProviderType' must be"
        )
        assert "workspace_credentials" in found.message
        assert "google_credentials" in found.message

    @pytest.mark.parametrize("value", ("workspace_credentials", 42, {"a": True}, [["a"]]))
    def test_wrong_type_costs_no_findings(self, tmp_path: Path, value) -> None:
        """A bad config line must not take every MCP finding with it."""
        body = '{"mcpServers": {"t": {"command": "x", "args": "--ro"}}}'
        violations = self._check(
            tmp_path,
            f"coerce-{type(value).__name__}",
            body,
            {"extra-auth-provider-types": value},
        )
        assert len(violations) == 1


class TestEveryRoot:
    """The rule reads all four customization roots and a plugin's own file."""

    @pytest.mark.parametrize("dirname", (".agents", ".agent", "_agents", "_agent"))
    def test_each_root(self, tmp_path: Path, dirname: str) -> None:
        violations = check(tmp_path, f"root-{dirname.lstrip('._')}", "[]", dirname=dirname)
        assert len(violations) == 1

    def test_plugin_mcp_file(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "plugin-mcp")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        (plugin / "mcp_config.json").write_text("[]", encoding="utf-8")
        violations = run_rule(AntigravityMcpValidRule, repo)
        assert len(violations) == 1
        assert violations[0].file_path == plugin / "mcp_config.json"


class TestGating:
    """``auto``, versioned, and gated on the two Antigravity types."""

    def test_rule_declares_the_release_it_shipped_in(self) -> None:
        assert AntigravityMcpValidRule.since == "0.20.0"
        assert AntigravityMcpValidRule.default_enabled == "auto"

    def test_repo_types(self) -> None:
        assert AntigravityMcpValidRule.repo_types == frozenset(
            {RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN}
        )

    def test_version_pin_below_the_release_reports_nothing(self, tmp_path: Path) -> None:
        """The ordinary state right after an upgrade must not turn red.

        Not only the new rule: ``mcp_config.json`` is a location this
        release put in the tree, so the shared MCP walk stands off it too
        rather than reporting a document the pinned results never held.
        """
        from tests.test_integration import run_lint

        repo = repo_with_mcp(tmp_path, "pinned", '{"mcpServers": }')
        (repo / ".skillsaw.yaml").write_text('version: "0.19.0"\n', encoding="utf-8")
        result = run_lint(repo)
        assert result["rc"] == 0
        assert (result["out"] or {}).get("violations", []) == []

    def test_a_version_pin_still_reports_a_committed_credential(self, tmp_path: Path) -> None:
        """The pin holds back the shape and the parse failure, never the secret."""
        from tests.test_integration import run_lint

        secret = "sk-live-" + "9f2c41a8" + "b7de4c6390af"  # assembled: no literal token in the tree
        body = (
            '{"mcpServers": {"t": {"url": "https://e.example", "oauth":'
            f' {{"clientId": "ferrymark", "clientSecret": "{secret}"}}}}}}}}'
        )
        repo = repo_with_mcp(tmp_path, "pinned-secret", body)
        (repo / ".skillsaw.yaml").write_text('version: "0.19.0"\n', encoding="utf-8")
        found = (run_lint(repo)["out"] or {}).get("violations", [])
        assert [v["rule_id"] for v in found] == ["mcp-valid-json"]
        assert "clientSecret" in found[0]["message"]
