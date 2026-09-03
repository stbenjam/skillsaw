"""Shared helpers for the Grok Build tests.

Grok's loader is silent about everything it refuses — a rejected file, a
dropped matcher group, a skipped event and a discarded handler all look like
a hook that had nothing to do — so these tests pin each verdict and its
scope individually rather than counting findings in bulk. The scopes come
from a canary matrix run against Grok Build 1.0.13; ``skillsaw.formats.grok``
records it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import LintTarget
from skillsaw.rule import RuleViolation, Severity
from skillsaw.rules.builtin.grok import GrokHooksValidRule
from tests.cli_runner import run_cli

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

#: A hooks file every helper below can drop into a repository unchanged.
HOOKS_JSON = '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "make lint"}]}]}}'


def copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name.replace("/", "_")
    shutil.copytree(FIXTURES / name, destination)
    return destination


def check(repo: Path, config: Optional[Dict[str, Any]] = None) -> List[RuleViolation]:
    return GrokHooksValidRule(config).check(RepositoryContext(repo))


def messages(violations: List[RuleViolation]) -> List[str]:
    return [violation.message for violation in violations]


def at(violations: List[RuleViolation], severity: Severity) -> List[str]:
    return [v.message for v in violations if v.severity == severity]


def only(violations: List[RuleViolation], needle: str) -> RuleViolation:
    """The one violation whose message contains *needle*."""
    found = [v for v in violations if needle in v.message]
    assert len(found) == 1, f"expected exactly one {needle!r} in {messages(violations)}"
    return found[0]


def relative(repo: Path, targets: List[LintTarget]) -> List[str]:
    return sorted(str(target.path.relative_to(repo)) for target in targets)


def lint_json(path: Path, *extra: object, returncode: int = 0) -> dict:
    """The CLI's JSON report, refusing to hide a run that fell over.

    Without the exit-code assertion a crash produces empty stdout, an empty
    report, and every ``== []`` assertion below passes vacuously.
    """
    result = run_cli(["lint", "--format", "json", "-v", path, *extra])
    assert result.returncode == returncode, result.stdout + result.stderr
    return json.loads(result.stdout)


def violations_for(report: dict, rule_id: str) -> List[dict]:
    return [v for v in report.get("violations", []) if v["rule_id"] == rule_id]


def write_repo(root: Path) -> Path:
    """A minimal but realistic repository root for hand-built cases."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text(
        "# Waypoint\n\nRun `make test` before pushing.\n",
    )
    return root


def write_hooks(root: Path, body: str, name: str = "hooks.json") -> Path:
    """Write *body* verbatim to ``<root>/.grok/hooks/<name>``.

    Verbatim because some cases are JSON no serializer will emit: ``NaN`` and
    ``Infinity`` are Python's spelling of a token the format does not have.
    """
    hooks_dir = root / ".grok" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    path = hooks_dir / name
    path.write_text(body)
    return path


def repo_with_hooks(tmp_path: Path, name: str, body: str) -> Path:
    """A repository whose only Grok content is one hooks file holding *body*."""
    repo = write_repo(tmp_path / name)
    write_hooks(repo, body)
    return repo
