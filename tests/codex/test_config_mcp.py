"""``[mcp_servers]`` in ``.codex/config.toml`` — Codex's project MCP layer.

There is no ``.codex/mcp.json``: a Codex project declares its servers in the
same file it declares its hooks in, and both are live only once the
developer's user config trusts the directory. These tests pin that the
tables reach ``mcp-prohibited`` with the shape an ``.mcp.json`` server has,
and that ``mcp-valid-json`` keeps its dialect-neutral checks while standing
its JSON shape walk down.

Measured against codex-cli 0.153.0 through ``codex mcp list --json``, which
prints the transport Codex derived for each server and runs offline.
"""

import json

import pytest

from skillsaw.blocks import CodexConfigBlock
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.mcp.prohibited import McpProhibitedRule
from skillsaw.rules.builtin.mcp.valid_json import McpValidJsonRule

from tests.cli_runner import run_cli

from ._helpers import copy_fixture, messages

_AGENTS_MD = "# Service\n\nRun `make test` before opening a pull request.\n"

_STDIO = """
[mcp_servers.postings]
command = "./scripts/postings-mcp"
args = ["--ledger", "nightly"]
"""


def _repo(tmp_path, body, *, name="repo"):
    repo = tmp_path / name
    (repo / ".codex").mkdir(parents=True)
    (repo / "AGENTS.md").write_text(_AGENTS_MD, encoding="utf-8")
    (repo / ".codex" / "config.toml").write_text(body, encoding="utf-8")
    return repo


def _block(repo):
    return RepositoryContext(repo).lint_tree.find(CodexConfigBlock)[0]


# ── What the block models ───────────────────────────────────────


class TestTheServerTables:
    def test_a_stdio_server_carries_its_command(self, tmp_path):
        server = _block(_repo(tmp_path, _STDIO)).servers[0]

        assert (server.name, server.type) == ("postings", "stdio")
        assert (server.command, server.args) == ("./scripts/postings-mcp", ["--ledger", "nightly"])

    def test_a_url_alone_is_streamable_http(self, tmp_path):
        """Codex has no ``type`` key: the transport follows from which
        connection field is present."""
        body = '[mcp_servers.rates]\nurl = "https://rates.example.test/mcp"\n'
        server = _block(_repo(tmp_path, body)).servers[0]

        assert (server.type, server.url) == ("http", "https://rates.example.test/mcp")

    def test_an_empty_command_is_still_stdio(self, tmp_path):
        """Measured: ``command = ""`` loads and ``codex mcp list`` reports a
        stdio server, where Grok drops the same table."""
        server = _block(_repo(tmp_path, '[mcp_servers.s]\ncommand = ""\n')).servers[0]

        assert server.type == "stdio"

    def test_a_table_naming_no_transport_is_dropped(self, tmp_path):
        """Measured fatal — ``invalid transport`` — so there is nothing to
        model, and the table is still in ``server_entries`` for a rule that
        wants to report it."""
        block = _block(_repo(tmp_path, "[mcp_servers.s]\nenabled = true\n"))

        assert block.servers == []
        assert [name for name, _ in block.server_entries()] == ["s"]

    def test_a_server_beside_a_malformed_sibling_is_still_seen(self, tmp_path):
        """A ``command`` beside a ``url`` refuses the whole file, measured,
        so nothing in it runs today — but every command in it is committed
        and one line away from live. Hiding a sibling behind a deliberate
        typo is not something the security scan should do."""
        body = _STDIO + '\n[mcp_servers.both]\ncommand = "./x.sh"\nurl = "https://x.example.test"\n'
        block = _block(_repo(tmp_path, body))

        assert {s.name for s in block.servers} == {"postings", "both"}

    def test_a_disabled_server_is_kept(self, tmp_path):
        body = _STDIO + '\n[mcp_servers.off]\ncommand = "./off.sh"\nenabled = false\n'

        assert {s.name for s in _block(_repo(tmp_path, body)).servers} == {"postings", "off"}

    def test_the_hooks_tables_are_not_servers(self, tmp_path):
        """``allow_bare_server_map`` is False: the file's other top-level
        tables are settings, not a bare server map."""
        body = '[[hooks.SessionStart]]\n\n[[hooks.SessionStart.hooks]]\ntype = "command"\ncommand = "./x.sh"\n'

        assert _block(_repo(tmp_path, body)).servers == []


# ── The rules that read them ────────────────────────────────────


class TestTheMcpRules:
    def test_mcp_prohibited_sees_a_project_server(self, tmp_path):
        found = McpProhibitedRule({}).check(RepositoryContext(_repo(tmp_path, _STDIO)))

        assert messages(found) == ["MCP servers defined in config.toml"]
        assert found[0].file_path.name == "config.toml"

    def test_an_allowlisted_server_is_permitted(self, tmp_path):
        config = {"allowlist": ["postings"]}

        assert McpProhibitedRule(config).check(RepositoryContext(_repo(tmp_path, _STDIO))) == []

    def test_a_package_layer_is_seen_too(self, tmp_path):
        """Codex merges a layer from every directory between the repository
        root and the session's cwd, measured."""
        repo = _repo(tmp_path, _STDIO)
        package = repo / "services" / "billing" / ".codex"
        package.mkdir(parents=True)
        (package / "config.toml").write_text(
            '[mcp_servers.billing]\ncommand = "./billing-mcp"\n', encoding="utf-8"
        )
        found = McpProhibitedRule({}).check(RepositoryContext(repo))

        assert len(found) == 2, messages(found)

    def test_a_credential_in_a_header_is_reported(self, tmp_path):
        """``http_headers`` is Codex's spelling of the header map, and a
        literal token in one is committed to the repository."""
        body = (
            "[mcp_servers.rates]\n"
            'url = "https://rates.example.test/mcp"\n'
            'http_headers = { Authorization = "Bearer 4f1c2ae87b03d9615a7e2c40b8d31f96" }\n'
        )
        found = McpValidJsonRule({}).check(RepositoryContext(_repo(tmp_path, body)))

        assert len(found) == 1, messages(found)
        assert "'Authorization' embeds" in found[0].message
        assert "4f1c2ae8" not in found[0].message

    def test_an_env_var_named_in_a_header_is_not_a_credential(self, tmp_path):
        """``env_http_headers`` values are the *names* of environment
        variables, which is the form that keeps a secret out of the file."""
        body = (
            "[mcp_servers.rates]\n"
            'url = "https://rates.example.test/mcp"\n'
            'env_http_headers = { Authorization = "RATES_MCP_TOKEN" }\n'
            'bearer_token_env_var = "RATES_MCP_TOKEN"\n'
        )

        assert McpValidJsonRule({}).check(RepositoryContext(_repo(tmp_path, body))) == []

    def test_a_url_carrying_userinfo_is_reported(self, tmp_path):
        body = '[mcp_servers.rates]\nurl = "https://user:pw@rates.example.test/mcp"\n'
        found = McpValidJsonRule({}).check(RepositoryContext(_repo(tmp_path, body)))

        assert len(found) == 1, messages(found)
        assert "must not contain user information" in found[0].message

    @pytest.mark.parametrize(
        "body",
        [
            # Every one of these is measured fatal — Codex names the server
            # and the field and exits 1 — so the shape is its own diagnostic
            # and skillsaw does not restate it.
            '[mcp_servers.s]\ncommand = "./x.sh"\nurl = "https://x.example.test"\n',
            "[mcp_servers.s]\nenabled = true\n",
            '[mcp_servers.s]\ncommand = "./x.sh"\nargs = "not-an-array"\n',
            '[mcp_servers.s]\ncommand = "./x.sh"\nbogus_server_key = 1\n',
        ],
    )
    def test_the_json_shape_walk_stands_down(self, tmp_path, body):
        """The shared walk reads a document the way the Claude family writes
        it, and would report a correct Codex config as invalid."""
        assert McpValidJsonRule({}).check(RepositoryContext(_repo(tmp_path, body))) == []

    def test_a_syntax_error_is_reported_once_by_the_hooks_rule(self, tmp_path):
        """One defect, one finding: ``codex-hooks-valid`` owns the parse
        failure for the whole file."""
        repo = _repo(tmp_path, "[mcp_servers.s\n")

        assert McpValidJsonRule({}).check(RepositoryContext(repo)) == []


# ── The fixtures ────────────────────────────────────────────────


class TestFixtures:
    def test_the_clean_fixture_declares_both_transports(self, tmp_path):
        repo = copy_fixture("codex/config-hooks-clean", tmp_path)
        servers = {s.name: s.type for s in _block(repo).servers}

        assert servers == {"postings": "stdio", "rates": "http"}

    def test_the_broken_fixtures_header_credential_is_reported(self, tmp_path):
        repo = copy_fixture("codex/config-hooks-broken", tmp_path)
        found = McpValidJsonRule({}).check(RepositoryContext(repo))

        assert len(found) == 1, messages(found)
        assert found[0].file_path.relative_to(repo).as_posix() == (
            "services/telemetry/.codex/config.toml"
        )

    def test_the_clean_fixture_reports_nothing(self, tmp_path):
        repo = copy_fixture("codex/config-hooks-clean", tmp_path)

        assert McpValidJsonRule({}).check(RepositoryContext(repo)) == []


@pytest.mark.integration
class TestThroughTheCli:
    def test_a_syntax_error_is_reported_once(self, tmp_path):
        """``mcp-valid-json`` declares ``codex-hooks-valid`` as the surface
        that owns the parse failure, so the linter path reports it once."""
        repo = copy_fixture("codex/config-hooks-broken", tmp_path)
        report = json.loads(run_cli(["lint", "--format", "json", str(repo)]).stdout)
        parse_errors = [
            v for v in report["violations"] if v["message"].startswith("Invalid TOML: ")
        ]

        assert [v["rule_id"] for v in parse_errors] == ["codex-hooks-valid"]

    def test_the_credential_is_reported_through_the_cli(self, tmp_path):
        repo = copy_fixture("codex/config-hooks-broken", tmp_path)
        report = json.loads(run_cli(["lint", "--format", "json", str(repo)]).stdout)
        found = [v for v in report["violations"] if v["rule_id"] == "mcp-valid-json"]

        assert len(found) == 1, found
        assert found[0]["file_path"] == "services/telemetry/.codex/config.toml"
