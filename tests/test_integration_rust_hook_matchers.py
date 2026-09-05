"""Both hook consumers accept Rust syntax under a warning exit threshold."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks.json_config import GrokHooksBlock, MuseHooksBlock
from skillsaw.context import RepositoryContext
from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture


@pytest.mark.integration
@pytest.mark.parametrize(
    "host,block_type,path",
    [
        ("grok", GrokHooksBlock, ".grok/hooks/matchers.json"),
        ("muse", MuseHooksBlock, ".muse/hooks.json"),
    ],
)
@pytest.mark.parametrize("outcome", ["valid", "invalid"])
def test_rust_matchers_use_host_dialect_in_cli(tmp_path, host, block_type, path, outcome):
    repo = copy_fixture(f"hooks/rust-matchers/{host}/{outcome}", tmp_path)
    blocks = RepositoryContext(repo).lint_tree.find(block_type)
    assert [str(b.path.relative_to(repo)) for b in blocks] == [path]
    rule = f"{host}-hooks-valid"
    result = run_cli(
        [
            "lint",
            str(repo),
            "--rule",
            rule,
            "--fail-on",
            "warning",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
            "--format",
            "json",
            "--verbose",
        ]
    )
    assert result.returncode == (0 if outcome == "valid" else 1), result.stderr
    report = json.loads(result.stdout)
    assert report["stats"]["rules_run"] == [rule]
    found = report["violations"]
    if outcome == "valid":
        assert found == []
    else:
        assert len(found) == 12
        assert {(v["rule_id"], v["file_path"], v["severity"]) for v in found} == {
            (rule, path, "warning")
        }
        for index in range(12):
            assert sum(f"PreToolUse[{index}] 'matcher'" in v["message"] for v in found) == 1
