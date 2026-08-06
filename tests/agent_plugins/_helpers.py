"""Shared helpers for Agent Plugins v1 tests."""

from pathlib import Path
import shutil
from typing import Optional, Set

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.linter import Linter

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
MANIFEST_RULE = "agent-plugin-manifest-valid"
MCP_RULE = "agent-plugin-mcp-valid"


def copy_fixture(name: str, tmp_path: Path) -> Path:
    """Copy one static fixture without dereferencing containment symlinks."""
    source = FIXTURES / name
    destination = tmp_path / name.replace("/", "_")
    shutil.copytree(source, destination, symlinks=True)
    return destination


def lint_rules(
    repo: Path,
    *rule_ids: str,
    repo_types: Optional[Set[RepositoryType]] = None,
):
    """Run only the requested built-in rules for one repository."""
    context = RepositoryContext(repo, repo_types=repo_types)
    config = LinterConfig.default()
    # Tests describe the branch's complete rule set, independently of the
    # installed package version used to create the virtual environment.
    config.version = "99.0.0"
    return Linter(context, config=config, rule_ids=set(rule_ids)).run()


def messages(findings) -> list[str]:
    return [finding.message for finding in findings]


def messages_lower(findings) -> list[str]:
    return [finding.message.lower() for finding in findings]
