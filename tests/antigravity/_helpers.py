"""Shared helpers for the Google Antigravity tests.

``agy`` is silent about almost everything it refuses: a rejected hooks file
contributes zero hooks and still exits 0, a dropped MCP server produces no
diagnostic at all, and a directory whose manifest does not parse is simply
not a plugin. So these tests pin each verdict and its *scope* individually
rather than counting findings in bulk. The scopes come from a matrix run
against ``agy`` 1.1.25 and 1.1.26; the maintenance reference records the method.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from skillsaw.context import RepositoryContext
from skillsaw.rule import RuleViolation, Severity

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name.replace("/", "_")
    # symlinks=True: a fixture that ships an escaping symlink is copied as
    # the symlink, not as the contents behind it — copying the contents
    # would rebuild the layout as an ordinary directory and quietly turn a
    # containment test into a no-op.
    shutil.copytree(FIXTURES / name, destination, symlinks=True)
    return destination


def run_rule(
    rule_cls: Any,
    repo: Path,
    config: Optional[Dict[str, Any]] = None,
    repo_types: Optional[Any] = None,
) -> List[RuleViolation]:
    """Findings *rule_cls* reports for the repository at *repo*."""
    return rule_cls(config).check(RepositoryContext(repo, repo_types=repo_types))


def messages(violations: List[RuleViolation]) -> List[str]:
    return [violation.message for violation in violations]


def at(violations: List[RuleViolation], severity: Severity) -> List[str]:
    return [v.message for v in violations if v.severity == severity]


def only(violations: List[RuleViolation], needle: str) -> RuleViolation:
    """The one violation whose message contains *needle*."""
    found = [v for v in violations if needle in v.message]
    assert len(found) == 1, f"expected exactly one {needle!r} in {messages(violations)}"
    return found[0]


def write_repo(root: Path) -> Path:
    """A minimal but realistic repository root for hand-built cases."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text(
        "# Ferrymark\n\nRun `make test` before pushing.\n", encoding="utf-8"
    )
    return root


def write_customization(root: Path, relative: str, body: str, dirname: str = ".agents") -> Path:
    """Write *body* verbatim under ``<root>/<dirname>/<relative>``.

    Verbatim because some cases are JSON no serializer will emit: a trailing
    comma and a bare ``NaN`` are the file ``agy``'s parser refuses, not a
    document with a value in it.
    """
    path = root / dirname / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def repo_with_hooks(tmp_path: Path, name: str, body: str, dirname: str = ".agents") -> Path:
    """A repository whose only Antigravity content is one ``hooks.json``."""
    repo = write_repo(tmp_path / name)
    write_customization(repo, "hooks.json", body, dirname)
    return repo


def repo_with_mcp(tmp_path: Path, name: str, body: str, dirname: str = ".agents") -> Path:
    """A repository whose only Antigravity content is one ``mcp_config.json``."""
    repo = write_repo(tmp_path / name)
    write_customization(repo, "mcp_config.json", body, dirname)
    return repo


def write_plugin(repo: Path, name: str, manifest: Optional[Dict[str, Any]]) -> Path:
    """A plugin directory under ``.agents/plugins/<name>``.

    ``None`` creates the directory with no manifest inside it, which is the
    "declared nothing" case: ``agy`` loads a directory as a plugin only when
    it carries a parseable ``plugin.json``.
    """
    plugin_dir = repo / ".agents" / "plugins" / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return plugin_dir
