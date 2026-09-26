"""Removal of the repository documentation generator in 0.21.0."""

import argparse
import shutil
from pathlib import Path

from skillsaw.cli import _SUBCOMMANDS
from skillsaw.cli._parser import _build_parser
from tests.cli_runner import run_cli

FIXTURES = Path(__file__).parent / "fixtures"


def copy_fixture(name, tmp_path):
    return Path(shutil.copytree(FIXTURES / name, tmp_path / name))


def test_docs_is_not_a_builtin_command():
    parser = _build_parser()
    subcommands = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    assert "docs" not in subcommands.choices
    assert "docs" not in _SUBCOMMANDS


def test_former_docs_arguments_cannot_generate_output(tmp_path):
    output = tmp_path / "generated.md"
    result = run_cli(["docs", tmp_path, "--format", "markdown", "-o", output])
    assert result.returncode == 2
    assert not output.exists()


def test_docs_command_stays_reserved(tmp_path):
    """An old CI step must not lint `docs` and overwrite the page it published."""
    repo = copy_fixture("removed-docs-command", tmp_path)
    site = repo / "site.html"
    published = site.read_bytes()

    result = run_cli(["docs", "--output", "site.html"], cwd=repo)

    assert result.returncode == 2
    assert "'skillsaw docs' was removed in 0.21.0" in result.stderr
    assert "skillsaw lint docs" in result.stderr
    assert result.stdout == ""
    assert site.read_bytes() == published


def test_docs_directory_is_still_a_lint_path(tmp_path):
    repo = copy_fixture("removed-docs-command", tmp_path)
    for args in (["lint", "docs"], ["./docs"]):
        result = run_cli([*args, "--rule", "agentskill-name"], cwd=repo)
        assert result.returncode == 0, result.stderr
        assert "removed" not in result.stderr
    assert not (repo / "skillsaw-docs").exists()
