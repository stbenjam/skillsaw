"""Grok 1.0.13 native-derived MCP variant and typed-field controls."""

from __future__ import annotations

import pytest

from skillsaw.blocks import GrokConfigBlock
from skillsaw.context import RepositoryContext
from tests.grok._helpers import copy_fixture, lint_json

RULE = "grok-config-valid"
URL = 'url = "https://docs.example.invalid/mcp"\n'
COMMAND = 'command = "docs-review-mcp"\n'
# Each case retains three independent servers and a permission-rule canary.
CASES = [
    ("stdio", COMMAND, "stdio", None),
    ("http", URL, "http", None),
    ("camel-alias", URL.replace("url =", "urlTemplate ="), "http", None),
    ("snake-alias", URL.replace("url =", "url_template ="), "http", None),
    ("stdio-first", COMMAND + URL, "stdio", None),
    ("stdio-ignored-url", COMMAND + "url = 42\n", "stdio", None),
    ("stdio-ignored-headers", COMMAND + "headers = 3\n", "stdio", None),
    ("stdio-ignored-header-value", COMMAND + "headers = { X-Project = false }\n", "stdio", None),
    ("stdio-ignored-type", COMMAND + "type = 42\n", "stdio", None),
    ("stdio-ignored-oauth-scopes", COMMAND + 'oauth_scopes = "unused"\n', "stdio", None),
    (
        "stdio-ignored-url-aliases",
        COMMAND + URL + URL.replace("url =", "urlTemplate ="),
        "stdio",
        None,
    ),
    ("http-ignored-command", URL + "command = 42\n", "http", None),
    ("http-ignored-args", URL + 'args = "unused"\n', "http", None),
    ("http-ignored-env", URL + "env = 42\n", "http", None),
    ("http-ignored-cwd", URL + "cwd = 42\n", "http", None),
    ("http-fallback-args", COMMAND + URL + "args = 42\n", "http", None),
    ("http-fallback-env", COMMAND + URL + "env = 42\n", "http", None),
    ("http-fallback-cwd", COMMAND + URL + "cwd = 42\n", "http", None),
    ("blank-stdio-before-http", 'command = ""\n' + URL, None, "'command' is empty"),
    ("blank-http", 'urlTemplate = " "\n', None, "'urlTemplate' is empty"),
    ("unicode-blank", 'command = "\\u3000"\n' + URL, None, "'command' is empty"),
    ("c0-not-blank", 'command = "\\u001c"\n', "stdio", None),
    ("disabled-blank", 'command = ""\nenabled = false\n' + URL, "stdio", None),
    ("disabled-missing", "enabled = false\n", None, "declares neither 'command' nor 'url'"),
    ("sse-uppercase", URL + 'type = "SSE"\n', "sse", None),
    ("sse-suffix", URL.replace("/mcp", "/sse"), "sse", None),
    ("sse-path-case", URL.replace("/mcp", "/SSE"), "http", None),
    ("unknown-type", URL + 'type = "future"\n', "http", None),
    ("unknown-field", URL + "future_field = 42\n", "http", None),
    (
        "alias-conflict",
        URL + URL.replace("url =", "urlTemplate ="),
        None,
        "are aliases; set only one",
    ),
    (
        "aliases-conflict",
        URL.replace("url =", "urlTemplate =") + URL.replace("url =", "url_template ="),
        None,
        "are aliases; set only one",
    ),
    (
        "both-variants-invalid",
        COMMAND + URL + "args = 42\nheaders = 42\n",
        None,
        "'args' must be an array of strings",
    ),
    (
        "u64-zero",
        URL + "startup_timeout_sec = 0\ntool_timeout_sec = 0\ntool_timeouts = { read = 0 }\n",
        "http",
        None,
    ),
    ("integer-max", URL + "startup_timeout_sec = 9223372036854775807\n", "http", None),
    ("oauth-empty", URL + "oauth = {}\n", "http", None),
    (
        "oauth-fields",
        URL
        + 'oauth = { clientId = "platform", clientSecretEnvVar = "PLATFORM_SECRET", scopes = ["read"], callbackPort = 65535 }\n',
        "http",
        None,
    ),
    ("oauth-unknown", URL + "oauth = { client_id = 42 }\n", "http", None),
    ("setup-empty", URL + "setup = {}\n", "http", None),
    (
        "setup-valid",
        URL
        + 'setup = { fields = [{ id = "site", label = "Site", type = "select", required = true, default = "eu", options = [{ label = "Europe", value = "eu" }] }], values = { region = { from = "site", map = { eu = "europe" } } } }\n',
        "http",
        None,
    ),
]

for field, value, reason in [
    ("command", "42", "must be a string"),
    ("args", '"bad"', "must be an array of strings"),
    ("args", '["read", 42]', "must be an array of strings"),
    ("env", "42", "must be a table of strings"),
    ("cwd", "42", "must be a string"),
]:
    body = ("" if field == "command" else COMMAND) + f"{field} = {value}\n"
    CASES.append(("bad-stdio-" + field + "-" + str(len(CASES)), body, None, reason))

for field, value, reason in [
    ("url", "42", "must be a string"),
    ("type", "42", "must be a string"),
    ("headers", "42", "must be a table of strings"),
    ("headers", "{ X-Project = true }", "must be a string"),
    ("bearer_token_env_var", "42", "must be a string"),
    ("oauth_client_id", "42", "must be a string"),
    ("oauth_client_secret_env_var", "42", "must be a string"),
    ("oauth_scopes", '"read"', "must be an array of strings"),
]:
    body = ("" if field == "url" else URL) + f"{field} = {value}\n"
    CASES.append(("bad-http-" + field + "-" + str(len(CASES)), body, None, reason))

for field, value, reason in [
    ("enabled", '"false"', "must be a boolean"),
    ("enabled", "1", "must be a boolean"),
    ("startup_timeout_sec", '"30"', "must be an integer from 0"),
    ("startup_timeout_sec", "-1", "must be an integer from 0"),
    ("tool_timeout_sec", "true", "must be an integer from 0"),
    ("tool_timeout_sec", "1.5", "must be an integer from 0"),
    ("tool_timeouts", "[]", "must be a table of unsigned integers"),
    ("tool_timeouts", '{ read = "30" }', "must be an integer from 0"),
    ("expose_image_base64", '"true"', "must be a boolean"),
    ("oauth", "true", "must be a table"),
    ("oauth", "{ clientId = 42 }", "must be a string"),
    ("oauth", "{ clientSecretEnvVar = 42 }", "must be a string"),
    ("oauth", '{ scopes = "read" }', "must be an array of strings"),
    ("oauth", "{ callbackPort = -1 }", "must be an integer from 0 to 65535"),
    ("oauth", "{ callbackPort = 65536 }", "must be an integer from 0 to 65535"),
    ("setup", '"command"', "must be a table"),
    ("setup", "{ fields = 42 }", "must be an array of tables"),
    ("setup", "{ fields = [{}] }", "is required"),
    (
        "setup",
        '{ fields = [{ id = "site", label = "Site", type = "Select" }] }',
        "must be 'select'",
    ),
    (
        "setup",
        '{ fields = [{ id = "site", label = "Site", type = "select", required = "true" }] }',
        "must be a boolean",
    ),
    (
        "setup",
        '{ fields = [{ id = "site", label = "Site", type = "select", options = [{}] }] }',
        "is required",
    ),
    (
        "setup",
        '{ fields = [{ id = "site", label = "Site", type = "select", options = [42] }] }',
        "must be an array of tables",
    ),
    ("setup", "{ variables = [], values = {} }", "must be a table"),
    ("setup", "{ variables = {}, values = {} }", "cannot both be set"),
    ("setup", "{ variables = { region = 42 } }", "must be a table"),
    ("setup", "{ values = { region = {} } }", "is required"),
    ("setup", '{ values = { region = { from = "site", map = { eu = 42 } } } }', "must be a string"),
]:
    for transport, connection in [("stdio", COMMAND), ("http", URL)]:
        CASES.append(
            (
                "bad-common-" + transport + "-" + field + "-" + str(len(CASES)),
                connection + f"{field} = {value}\n",
                None,
                reason,
            )
        )


def fixture(tmp_path, body=None):
    repo = copy_fixture("grok/config-transports", tmp_path)
    if body is not None:
        path = repo / ".grok/config.toml"
        text = path.read_text()
        start = text.index("[mcp_servers.docs]")
        end = text.index("# The issue provider")
        path.write_text(text[:start] + "[mcp_servers.docs]\n" + body + "\n" + text[end:])
    return repo


def inspect_lint(repo):
    report = lint_json(
        repo,
        "--rule",
        RULE,
        "--rule",
        "grok-config-project-scope",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert set(report["stats"]["rules_run"]) == {RULE, "grok-config-project-scope"}
    assert "grok-project" in report["stats"]["repo_types"]
    blocks = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)
    assert [block.path for block in blocks] == [repo / ".grok/config.toml"]
    block = blocks[0]
    assert set(dict(block.server_entries())) == {"docs", "issues", "migrations", "canary"}
    servers = {server.name: server for server in block.servers}
    assert servers["canary"].command == "catalog-review-mcp"
    assert servers["canary"].args == ["--read-only"]
    assert servers["issues"].url == "https://issues.example.invalid/mcp"
    assert servers["migrations"].type == "http"
    assert servers["migrations"].command is None
    assert servers["migrations"].args is None
    assert block.permission == {"allow": ["Read"]}
    return report["violations"], servers


def test_static_aliases_and_fallback_keep_normalized_servers(tmp_path):
    found, servers = inspect_lint(fixture(tmp_path))
    assert found == []
    assert servers["docs"].url == "https://docs.example.invalid/mcp"
    assert servers["docs"].headers == {"X-Project": "platform"}


@pytest.mark.parametrize("name,body,transport,reason", CASES, ids=[row[0] for row in CASES])
def test_mcp_decoder_matches_native_variant_controls(tmp_path, name, body, transport, reason):
    found, servers = inspect_lint(fixture(tmp_path, body))
    if reason is None:
        assert found == []
        assert servers["docs"].type == transport
        if transport == "stdio":
            assert servers["docs"].url is None
            assert servers["docs"].headers is None
        else:
            assert servers["docs"].command is None
            assert servers["docs"].args is None
            assert servers["docs"].env is None
            assert servers["docs"].cwd is None
        if name == "u64-zero":
            assert servers["docs"].startup_timeout == 0
            assert servers["docs"].timeout == 0
    else:
        assert "docs" not in servers
        assert len(found) == 1
        assert (found[0]["rule_id"], found[0]["file_path"]) == (RULE, ".grok/config.toml")
        assert reason in found[0]["message"]


def test_nested_type_failures_stay_one_bounded_server_finding(tmp_path):
    found, _servers = inspect_lint(fixture(tmp_path, URL + "setup = { fields = [{}, {}, {}] }\n"))
    assert len(found) == 1
    assert found[0]["message"] == (
        "[mcp_servers.docs] 'setup.fields[1].id' is required, "
        "'setup.fields[1].label' is required, 'setup.fields[1].type' is required, and 6 more"
    )
