"""Field-level checks behind zcode-hooks-valid and zcode-config-valid."""

from __future__ import annotations

import pytest

from skillsaw.rules.builtin.zcode._helpers import matcher_group_problems
from skillsaw.rules.builtin.zcode.config_valid import ZCodeConfigValidRule


def _group(**handler):
    return {"hooks": [{"type": "command", "command": "make lint", **handler}]}


@pytest.mark.parametrize(
    ("group", "project", "expected"),
    [
        (_group(), False, None),
        ("not a group", False, "must be an object"),
        ({"matcher": 3, **_group()}, False, "'matcher' must be a string"),
        ({"matcher": "", **_group()}, True, "'matcher' must be a non-empty string"),
        ({"matcher": "", **_group()}, False, None),
        ({"hooks": []}, False, "non-empty array"),
        ({"hooks": ["make"]}, False, "hooks[0] must be an object"),
        ({"hooks": [{"type": "command"}]}, False, "command must be a non-empty string"),
        (_group(enabled="yes"), False, "enabled must be a boolean"),
        (_group(onError="ignore"), False, "onError must be 'allow' or 'deny'"),
        (_group(statusMessage=""), True, "statusMessage must be a string"),
        (_group(statusMessage=""), False, None),
        (_group(timeoutMs=1.5), False, "timeoutMs must be a positive integer"),
        (_group(timeoutMs=1.5), True, None),
        (_group(timeoutMs=0), True, "timeoutMs must be a positive number"),
        (_group(timeoutMs=True), False, "timeoutMs must be a positive integer"),
        (_group(**{"async": "yes"}), False, "async must be a boolean"),
        (_group(shell=False), False, "shell must be true or a non-empty string"),
        (_group(shell=True), False, None),
        (_group(shell="bash"), False, None),
        (_group(timeout=-1), False, "timeout must be a positive number"),
        (
            {"hooks": [{"type": "process", "command": "make", "args": "lint"}]},
            False,
            "args must be an array of strings",
        ),
        ({"hooks": [{"type": "process", "command": "make", "args": ["lint"]}]}, False, None),
    ],
)
def test_matcher_group_problems(group, project, expected):
    problems = matcher_group_problems(group, project=project)
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


@pytest.mark.parametrize(
    ("server", "expected"),
    [
        ({"type": "stdio", "command": "db-mcp"}, ""),
        ({"command": "db-mcp", "environment": {"A": "b"}, "timeout": 30}, ""),
        ({"type": "remote", "url": "https://example.com/mcp"}, ""),
        ({"url": "https://example.com/mcp", "http_headers": {"X": "y"}}, ""),
        ("db-mcp", "must be an object"),
        ({"args": ["x"]}, "has no 'type'"),
        ({"type": "ws", "url": "wss://example.com"}, "'type' must be stdio, http or sse"),
        ({"type": "sse", "url": "https://e.com", "cwd": "/"}, "unknown key(s) for an sse"),
        ({"type": "stdio", "command": ""}, "a stdio server needs a non-empty 'command'"),
        ({"command": "db-mcp", "env": {"PORT": 5432}}, "'env' must be an object of string"),
        ({"command": "db-mcp", "args": "--readonly"}, "'args' must be an array of strings"),
    ],
)
def test_server_problem(server, expected):
    problem = ZCodeConfigValidRule._server_problem(server)
    assert (expected in problem) if expected else problem == ""


@pytest.mark.parametrize(
    ("hooks", "expected"),
    [
        ({"enabled": True, "timeoutMs": 1000, "maxOutputBytes": 4096, "events": {}}, None),
        ([], "'hooks' must be an object"),
        ({"enabled": "on"}, "'hooks.enabled' must be a boolean"),
        ({"maxOutputBytes": -1}, "'hooks.maxOutputBytes' must be a positive number"),
        ({"events": []}, "'hooks.events' must be an object"),
        ({"events": {"Stop": {}}}, "'hooks.events.Stop' must be an array"),
    ],
)
def test_hooks_problems(hooks, expected):
    problems = ZCodeConfigValidRule._hooks_problems(hooks)
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems
