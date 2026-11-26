"""Conformance of skillsaw with ``claude plugin validate`` on the Claude fixtures.

``tests/claude_conformance.json`` records, for every fixture holding a
``.claude-plugin/``, what Claude Code's validator says will not load and
which rules skillsaw reports as errors. The skillsaw half runs everywhere;
the validator half runs only with the pinned ``claude`` CLI installed.
Re-record with ``scripts/claude-conformance.py --write``.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from tests.cli_runner import run_cli

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "claude_conformance", ROOT / "scripts" / "claude-conformance.py"
)
conformance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conformance)

MANIFEST = conformance.load_manifest()
FIXTURES = conformance.fixture_dirs()
PINNED = MANIFEST["claude_code_version"]


def _lint(path):
    result = run_cli(["lint", "--format", "json", "--no-progress", path])
    return json.loads(result.stdout)


def test_manifest_lists_every_claude_fixture():
    assert sorted(MANIFEST["fixtures"]) == FIXTURES


def test_every_one_sided_result_is_explained():
    unexplained = [
        name
        for name, entry in MANIFEST["fixtures"].items()
        if bool(entry["official"]) != bool(entry["skillsaw"]) and not entry.get("note")
    ]
    assert unexplained == [], "add a 'note' saying why only one side reports an error"


@pytest.mark.parametrize("fixture", FIXTURES)
def test_skillsaw_matches_manifest(fixture):
    expected = MANIFEST["fixtures"][fixture]["skillsaw"]
    assert conformance.skillsaw_errors(fixture, lint=_lint) == expected


@pytest.mark.claude_conformance
@pytest.mark.parametrize("fixture", FIXTURES)
def test_claude_validate_matches_manifest(fixture):
    version = conformance.claude_version()
    if version is None:
        pytest.skip("claude CLI not installed")
    if version != PINNED:
        pytest.skip(f"manifest pins Claude Code {PINNED}, found {version}")
    expected = MANIFEST["fixtures"][fixture]["official"]
    assert conformance.official_failures(fixture) == expected
