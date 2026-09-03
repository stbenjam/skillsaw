"""Grok Build's project ``config.toml``: attachment and the MCP role.

Grok reads the ``.grok/`` layer of the project it is started in, so a
monorepo package's ``config.toml`` is live configuration and gets a block of
its own. The file is also where a Grok project declares its MCP servers —
there is no ``.grok/mcp.json`` — which is why the block carries the shared
MCP role rather than being an opaque config node.
"""

from __future__ import annotations

import pytest

from skillsaw.blocks import GrokConfigBlock, McpConfigRole
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.mcp import McpProhibitedRule, McpValidJsonRule

from tests.grok._helpers import (
    copy_fixture,
    lint_json,
    messages,
    relative,
    run_rule,
    write_config,
    write_repo,
)

#: One stdio server and one HTTP server, spelled the way the shipped
#: ``26-config-reference.md`` spells them.
SERVERS = """\
[mcp_servers.berths]
command = "bin/harbourmaster"
args = ["mcp", "--read-only"]

[mcp_servers.tideboard]
url = "https://tideboard.internal.example/mcp"
"""


# ── Detection ────────────────────────────────────────────────────


def test_config_toml_is_still_grok_project_evidence(temp_dir) -> None:
    """Attaching the file must not change what it detects: ``config.toml``
    alone made the directory Grok's before it was parsed, and still does."""
    write_config(temp_dir, SERVERS)

    assert RepositoryType.GROK_PROJECT in RepositoryContext(temp_dir).repo_types


# ── Attachment ───────────────────────────────────────────────────


def test_the_project_config_attaches_at_the_root(temp_dir) -> None:
    repo = write_repo(temp_dir / "repo")
    write_config(repo, SERVERS)

    blocks = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)

    assert relative(repo, blocks) == [".grok/config.toml"]
    assert blocks[0].tree_label() == "config.toml [grok]"


def test_a_package_keeps_its_own_config(temp_dir) -> None:
    """Grok reads the layer of the directory it is started in, so a package's
    file is configuration in its own right rather than an override."""
    repo = write_repo(temp_dir / "repo")
    write_config(repo, SERVERS)
    write_config(repo / "packages" / "gantry", "[permission]\nallow = []\n")

    blocks = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)

    assert relative(repo, blocks) == [
        ".grok/config.toml",
        "packages/gantry/.grok/config.toml",
    ]


def test_one_block_per_file(temp_dir) -> None:
    """The MCP role and the config role are one node, not two: a second block
    over the same file would report each of its servers twice."""
    repo = write_repo(temp_dir / "repo")
    write_config(repo, SERVERS)

    tree = RepositoryContext(repo).lint_tree

    assert len(tree.find(GrokConfigBlock)) == 1
    assert len(tree.find(McpConfigRole)) == 1


def test_the_broken_fixture_attaches_every_package_config(tmp_path) -> None:
    repo = copy_fixture("grok/config-broken", tmp_path)

    blocks = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)

    assert relative(repo, blocks) == [
        ".grok/config.toml",
        "packages/bollard/.grok/config.toml",
        "packages/dredger/.grok/config.toml",
        "packages/gantry/.grok/config.toml",
        "packages/lockgate/.grok/config.toml",
        "packages/manifest/.grok/config.toml",
        "packages/mooring/.grok/config.toml",
        "packages/pilotage/.grok/config.toml",
        "packages/quayside/.grok/config.toml",
        "packages/reefer/.grok/config.toml",
        "packages/stevedore/.grok/config.toml",
        "packages/tugs/.grok/config.toml",
    ]


def test_an_excluded_project_layer_drops_the_config(temp_dir) -> None:
    repo = write_repo(temp_dir / "repo")
    write_config(repo, SERVERS)

    context = RepositoryContext(repo, exclude_patterns=[".grok/**"])

    assert context.lint_tree.find(GrokConfigBlock) == []


def test_a_config_symlinked_out_of_the_checkout_is_not_attached(temp_dir) -> None:
    """A symlink out of the checkout is a file the linter would read, publish
    and, once a fix lands, rewrite."""
    outside = temp_dir / "outside-the-checkout"
    outside.mkdir()
    (outside / "config.toml").write_text(SERVERS, encoding="utf-8")
    repo = write_repo(temp_dir / "repo")
    (repo / ".grok").mkdir()
    (repo / ".grok" / "config.toml").symlink_to(outside / "config.toml")

    assert RepositoryContext(repo).lint_tree.find(GrokConfigBlock) == []


# ── Parsing ──────────────────────────────────────────────────────


def test_a_parsed_config_exposes_its_tables(temp_dir) -> None:
    repo = write_repo(temp_dir / "repo")
    write_config(repo, SERVERS + '\n[plugins]\nenabled = ["tide-charts"]\n')

    block = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)[0]

    assert block.parse_error is None
    assert set(block.raw_data) == {"mcp_servers", "plugins"}


def test_a_malformed_config_still_yields_a_block(temp_dir) -> None:
    """The rule that reports the parse error needs something to report on."""
    repo = write_repo(temp_dir / "repo")
    write_config(repo, '[mcp_servers.gantry]\ncommand = "bin/gantry"\nargs = ["mcp"\n')

    blocks = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)

    assert relative(repo, blocks) == [".grok/config.toml"]
    assert blocks[0].raw_data is None
    assert "Unclosed array" in blocks[0].parse_error


# ── The MCP role ─────────────────────────────────────────────────


def test_the_mcp_servers_table_reads_as_servers(temp_dir) -> None:
    repo = write_repo(temp_dir / "repo")
    write_config(repo, SERVERS)

    block = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)[0]

    assert block.server_names == {"berths", "tideboard"}
    by_name = {server.name: server for server in block.servers}
    assert by_name["berths"].command == "bin/harbourmaster"
    assert by_name["berths"].args == ["mcp", "--read-only"]
    assert by_name["berths"].type == "stdio"
    assert by_name["tideboard"].url == "https://tideboard.internal.example/mcp"
    assert by_name["tideboard"].type == "http"


@pytest.mark.parametrize(
    "table, expected",
    [
        # A non-empty command wins even beside a url.
        ('command = "bin/berths"\nurl = "https://berths.example/mcp"\n', "stdio"),
        # type is advisory: it never overrides a command.
        ('type = "http"\ncommand = "bin/berths"\n', "stdio"),
        ('url = "https://berths.example/mcp"\n', "http"),
        ('type = "sse"\nurl = "https://berths.example/mcp"\n', "sse"),
        # transport is not an alias for type; Grok ignores it.
        ('transport = "sse"\nurl = "https://berths.example/mcp"\n', "http"),
        # Content is never validated.
        ('url = "not a url"\n', "http"),
    ],
)
def test_the_transport_is_derived_the_way_grok_derives_it(temp_dir, table, expected) -> None:
    repo = write_repo(temp_dir / "repo")
    write_config(repo, "[mcp_servers.berths]\n" + table)

    block = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)[0]

    assert [server.type for server in block.servers] == [expected]


@pytest.mark.parametrize("table", ['args = ["mcp"]\n', 'command = ""\n'])
def test_a_server_grok_drops_is_not_exposed_as_one(temp_dir, table) -> None:
    """Neither field names anything Grok can start, so it loads no server —
    and the policy rules must describe what runs. The table is still in
    ``server_entries()``, where the config rule finds it."""
    repo = write_repo(temp_dir / "repo")
    write_config(
        repo,
        "[mcp_servers.quayside]\n" + table + '\n[mcp_servers.berths]\ncommand = "bin/berths"\n',
    )

    block = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)[0]

    assert block.server_names == {"berths"}
    assert [name for name, _ in block.server_entries()] == ["quayside", "berths"]


def test_a_disabled_server_is_still_scanned(temp_dir) -> None:
    """Grok omits it from ``inspect``, but the command is committed and a
    one-word edit turns it on."""
    repo = write_repo(temp_dir / "repo")
    write_config(
        repo,
        '[mcp_servers.berths]\ncommand = "bin/harbourmaster"\nenabled = false\n',
    )

    block = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)[0]

    assert block.server_names == {"berths"}


def test_a_non_table_mcp_servers_costs_only_that_table(temp_dir) -> None:
    repo = write_repo(temp_dir / "repo")
    write_config(repo, 'mcp_servers = "servers.json"\n\n[permission]\nallow = []\n')

    block = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)[0]

    assert block.server_names == set()
    assert block.permission == {"allow": []}


# ── The permission table ─────────────────────────────────────────


def test_the_permission_table_is_exposed(temp_dir) -> None:
    """The other honoured table, and the one Grok says nothing about."""
    repo = write_repo(temp_dir / "repo")
    write_config(
        repo,
        '[permission]\nallow = ["Bash(make test)"]\ndeny = ["Bash(psql *)"]\n',
    )

    block = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)[0]

    assert block.permission == {"allow": ["Bash(make test)"], "deny": ["Bash(psql *)"]}


def test_no_permission_table_reads_as_none(temp_dir) -> None:
    repo = write_repo(temp_dir / "repo")
    write_config(repo, SERVERS)

    assert RepositoryContext(repo).lint_tree.find(GrokConfigBlock)[0].permission is None


def test_the_other_project_tables_are_not_servers(temp_dir) -> None:
    """TOML has no bare-map form to fall back to, so ``[permission]`` and
    ``[plugins]`` beside the servers are configuration, not a server map."""
    repo = write_repo(temp_dir / "repo")
    write_config(repo, "[permission]\nallow = []\n\n[plugins]\nenabled = []\n")

    block = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)[0]

    assert block.server_names == set()


def test_mcp_prohibited_sees_a_toml_server(temp_dir) -> None:
    """The whole point of the role: the policy rule reads Grok's servers with
    no knowledge that this one is TOML."""
    repo = write_repo(temp_dir / "repo")
    write_config(
        repo,
        '[mcp_servers.paged-out]\ncommand = "npx"\nargs = ["-y", "@paged/out"]\n',
    )

    found = run_rule(McpProhibitedRule, repo, {"allowlist": ["berths"]})

    assert messages(found) == ["non-allowlisted MCP servers defined: paged-out"]


def test_mcp_valid_json_leaves_the_toml_shape_alone(temp_dir) -> None:
    """A config declaring only ``[permission]`` declares no servers on
    purpose; the JSON rule's "no server key" branch would call that a
    defect, so it stands down for this dialect."""
    repo = write_repo(temp_dir / "repo")
    write_config(repo, '[permission]\nallow = ["Bash(make test)"]\n')

    assert run_rule(McpValidJsonRule, repo) == []


def test_mcp_valid_json_does_not_announce_a_toml_parse_error_as_json(temp_dir) -> None:
    repo = write_repo(temp_dir / "repo")
    write_config(repo, "[mcp_servers.gantry\n")

    assert run_rule(McpValidJsonRule, repo) == []


def test_mcp_valid_json_keeps_the_dialect_neutral_credential_check(temp_dir) -> None:
    """What a *server* must not carry is the same in every dialect, so the
    checks that do not read the document's shape stay."""
    repo = write_repo(temp_dir / "repo")
    write_config(
        repo,
        "[mcp_servers.tideboard]\n"
        'type = "http"\n'
        'url = "https://operator:hunter2@tideboard.internal.example/mcp"\n',
    )

    found = run_rule(McpValidJsonRule, repo)

    assert messages(found) == ["MCP server 'tideboard' 'url' must not contain user information"]


# ── End to end ───────────────────────────────────────────────────


def test_the_clean_fixture_reports_nothing(tmp_path) -> None:
    repo = copy_fixture("grok/config-clean", tmp_path)

    assert lint_json(repo)["violations"] == []


def test_only_the_config_rules_read_the_broken_fixture(tmp_path) -> None:
    """A noise gate: every defect in this fixture belongs to the two config
    rules, and attaching a TOML file must not hand it to anything else — a
    content rule reading it would be linting configuration as prose."""
    repo = copy_fixture("grok/config-broken", tmp_path)

    report = lint_json(repo, returncode=1)

    assert {v["rule_id"] for v in report["violations"]} == {
        "grok-config-valid",
        "grok-config-project-scope",
    }
