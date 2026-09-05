"""Native workspace permission decoder controls for Grok 1.0.13."""

from __future__ import annotations

import pytest

from skillsaw.blocks import GrokConfigBlock
from skillsaw.context import RepositoryContext
from tests.grok._helpers import copy_fixture, lint_json

RULE = "grok-config-valid"
CANARY_RULE = '{ action = "allow", tool = "read", pattern = "docs/**" }'
VALID_RULES = "rules = [" + CANARY_RULE + ', { action = "ask", tool = "edit" }]\n'
CASES = [
    ("verbose", VALID_RULES, 2, []),
    ("empty-rules", "rules = []\n", 0, []),
    ("omitted-rules", "future_field = 42\n", 0, []),
    (
        "compact-precedence",
        'allow = ["Read"]\n' + VALID_RULES,
        1,
        ["'rules' is discarded because 'allow' is also set"],
    ),
    (
        "compact-empty",
        "allow = []\n" + VALID_RULES,
        0,
        ["'rules' is discarded because 'allow' is also set"],
    ),
    ("compact-empty-rules", 'allow = ["Read"]\nrules = []\n', 1, []),
    ("compact-bad-type", 'allow = "Read"\n' + VALID_RULES, 2, ["'allow' must be an array"]),
    ("compact-only-bad-type", 'allow = "Read"\n', 0, ["'allow' must be an array"]),
    (
        "compact-mixed-types",
        'allow = ["Read", 42]\n' + VALID_RULES,
        1,
        ["Grok drops entry 2", "'rules' is discarded"],
    ),
    (
        "compact-bad-value-array",
        "allow = [42]\n" + VALID_RULES,
        0,
        ["Grok drops entry 1", "'rules' is discarded"],
    ),
    (
        "mixed-compact-keys",
        'allow = "Read"\ndeny = []\n' + VALID_RULES,
        0,
        ["'allow' must be an array", "because 'deny' is also set"],
    ),
    (
        "ignored-verbose-fields",
        'allow = ["Read"]\nprompt_policy = 42\ndefault_mode_configured = "true"\n',
        1,
        [],
    ),
    ("missing-tool", "rules = [" + CANARY_RULE + ', { action = "ask" }]\n', 2, []),
    (
        "unknown-rule-field",
        "rules = [" + CANARY_RULE + ', { action = "ask", future_field = 42 }]\n',
        2,
        [],
    ),
    (
        "missing-action",
        "rules = [" + CANARY_RULE + ', { tool = "read" }]\n',
        0,
        ["entry 2: missing required 'action'"],
    ),
    (
        "non-table",
        "rules = [" + CANARY_RULE + ", 42]\n",
        0,
        ["entries must be rule tables or field arrays"],
    ),
    ("rules-type", 'rules = "Read"\n', 0, ["'rules' must be an array of tables"]),
    ("top-level-scalar", 'permission = "allow-all"\n', 0, ["'permission' must be a table"]),
    ("default-mode-bool", "default_mode_configured = false\n" + VALID_RULES, 2, []),
    (
        "default-mode-invalid",
        'default_mode_configured = "false"\n' + VALID_RULES,
        0,
        ["'default_mode_configured' must be a boolean"],
    ),
]
for field, accepted in [
    ("action", ["allow", "deny", "ask"]),
    (
        "tool",
        [
            "any",
            "bash",
            "edit",
            "read",
            "grep",
            "mcp",
            "webfetch",
            "websearch",
            "agent_message",
            "agentmessage",
        ],
    ),
    ("pattern_mode", ["glob", "domain"]),
    ("pattern", ["", "[unclosed", "**/src/**"]),
]:
    for value in accepted:
        rule = ("" if field == "action" else 'action = "ask", ') + f'{field} = "{value}"'
        CASES.append(
            (
                "accepted-" + field + "-" + str(len(CASES)),
                "rules = [" + CANARY_RULE + ", {" + rule + "}]\n",
                2,
                [],
            )
        )
for field, value in [
    ("action", '"Allow"'),
    ("action", '"maybe"'),
    ("action", "42"),
    ("tool", '"Read"'),
    ("tool", '"MCPTool"'),
    ("tool", '"future_tool"'),
    ("tool", '["read"]'),
    ("pattern_mode", '"Glob"'),
    ("pattern_mode", '"regex"'),
    ("pattern_mode", "42"),
    ("pattern", "42"),
    ("pattern", '["docs/**"]'),
]:
    rule = ("" if field == "action" else 'action = "ask", ') + f"{field} = {value}"
    CASES.append(
        (
            "rejected-" + field + "-" + str(len(CASES)),
            "rules = [" + CANARY_RULE + ", {" + rule + "}]\n",
            0,
            [f"entry 2: '{field}' must be"],
        )
    )
for value in ["ask", "deny", "auto", "allow"]:
    CASES.append(
        ("prompt-policy-" + value, 'prompt_policy = "' + value + '"\n' + VALID_RULES, 2, [])
    )
for value in ['"Ask"', '"future"', "42"]:
    CASES.append(
        (
            "bad-policy-" + str(len(CASES)),
            "prompt_policy = " + value + "\n" + VALID_RULES,
            0,
            ["'prompt_policy' must be one of"],
        )
    )

for field, variant in [
    ("action", "allow"),
    ("tool", "read"),
    ("pattern_mode", "glob"),
    ("prompt_policy", "ask"),
]:
    for body, valid in [("{}", True), ("[]", True), ("{ ignored = 42 }", False), ("[42]", False)]:
        value = "{ " + variant + " = " + body + " }"
        if field == "prompt_policy":
            config = "prompt_policy = " + value + "\n" + VALID_RULES
            error = "'prompt_policy' must be"
        else:
            rule = ("" if field == "action" else 'action = "ask", ') + field + " = " + value
            config = "rules = [" + CANARY_RULE + ", {" + rule + "}]\n"
            error = "entry 2: '" + field + "' must be"
        CASES.append(
            (
                "enum-table-" + field + "-" + str(len(CASES)),
                config,
                2 if valid else 0,
                [] if valid else [error],
            )
        )

for name, body, loaded, expected in [
    ("top-array", 'permission = [[["allow", "read", "docs/**", "glob"]], "ask", false]\n', 1, []),
    ("empty-top-array", "permission = []\n", 0, []),
    ("rule-array", 'rules = [["allow", "read", "docs/**", "glob"]]\n', 1, []),
    ("default-mode-array", 'rules = [["allow", "read", "docs/**"]]\n', 1, []),
    (
        "short-rule-array",
        "rules = [" + CANARY_RULE + ', ["allow", "read"]]\n',
        0,
        ["entries must be rule tables or field arrays"],
    ),
    (
        "long-rule-array",
        "rules = [" + CANARY_RULE + ', ["allow", "read", "docs/**", "glob", "extra"]]\n',
        0,
        ["entries must be rule tables or field arrays"],
    ),
]:
    CASES.append((name, body, loaded, expected))


def fixture(tmp_path, body=None):
    repo = copy_fixture("grok/config-permissions", tmp_path)
    if body is not None:
        path = repo / ".grok/config.toml"
        before = path.read_text().split("[permission]")[0]
        path.write_text(
            (body + before) if body.startswith("permission =") else before + "[permission]\n" + body
        )
    return repo


def report(repo):
    data = lint_json(repo, "--rule", RULE, "--no-custom-rules", "--no-plugins", "--no-baseline")
    assert data["stats"]["rules_run"] == [RULE]
    assert "grok-project" in data["stats"]["repo_types"]
    blocks = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)
    assert [b.path for b in blocks] == [repo / ".grok/config.toml"]
    assert [(s.name, s.type, s.command, s.args) for s in blocks[0].servers] == [
        ("canary", "stdio", "catalog-review-mcp", ["--read-only"])
    ]
    return data["violations"]


def test_static_verbose_permission_fixture_is_valid(tmp_path):
    assert report(fixture(tmp_path)) == []


@pytest.mark.parametrize("name,body,loaded,expected", CASES, ids=[row[0] for row in CASES])
def test_permission_decoder_matches_native_controls(tmp_path, name, body, loaded, expected):
    found = report(fixture(tmp_path, body))
    assert len(found) == len(expected)
    for finding, message in zip(found, expected):
        assert (finding["rule_id"], finding["file_path"]) == (RULE, ".grok/config.toml")
        assert message in finding["message"]
