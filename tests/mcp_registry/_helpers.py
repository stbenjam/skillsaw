"""Shared helpers for MCP Registry publisher metadata tests."""

from pathlib import Path
import shutil
from typing import Any, Dict, Optional, Set

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.linter import Linter

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
VALID_RULE = "mcp-registry-server-json-valid"
SEMVER_RULE = "mcp-registry-version-semver"
NPM_NAME_RULE = "mcp-registry-npm-name-match"


def copy_fixture(name: str, tmp_path: Path) -> Path:
    source = FIXTURES / name
    destination = tmp_path / name.replace("/", "_")
    shutil.copytree(source, destination, symlinks=True)
    return destination


def lint_rules(
    repo: Path,
    *rule_ids: str,
    repo_types: Optional[Set[RepositoryType]] = None,
    rule_config: Optional[Dict[str, Dict[str, Any]]] = None,
):
    context = RepositoryContext(repo, repo_types=repo_types)
    config = LinterConfig.default()
    config.version = "99.0.0"
    for rule_id, options in (rule_config or {}).items():
        config.rules.setdefault(rule_id, {}).update(options)
    return Linter(context, config=config, rule_ids=set(rule_ids)).run()


def messages_lower(findings) -> list[str]:
    return [finding.message.lower() for finding in findings]
