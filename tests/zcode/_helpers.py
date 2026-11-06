"""Shared helpers for the ZCode tests.

The expected verdicts come from ZCode's loader source (``zai-org/ZCode`` at
``a9fe401e``); ``skillsaw.formats.zcode`` cites the file and line of each.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from tests.cli_runner import run_cli

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name.replace("/", "_")
    shutil.copytree(FIXTURES / name, destination, symlinks=True)
    return destination


def lint(repo: Path, *extra: str) -> Dict[str, Any]:
    """Run ``skillsaw lint --format json -v`` and return the parsed report."""
    result = run_cli(["lint", "--format", "json", "-v", str(repo), *extra])
    report = json.loads(result.stdout)
    report["rc"] = result.returncode
    return report


def findings(report: Dict[str, Any], rule_id: str) -> List[Dict[str, Any]]:
    return [v for v in report["violations"] if v["rule_id"] == rule_id]


def messages(report: Dict[str, Any], rule_id: str) -> List[str]:
    return [v["message"] for v in findings(report, rule_id)]


def rule_ids(report: Dict[str, Any]) -> set:
    return {v["rule_id"] for v in report["violations"]}


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path
