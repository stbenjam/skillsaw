"""OpenClaw package JSON stays strict while native manifests accept JSON5."""

import json
import shutil
from pathlib import Path

import pytest

from skillsaw.discovery.openclaw import declares_extensions
from tests.cli_runner import run_cli

FIXTURES = Path(__file__).parent / "fixtures" / "openclaw-package-json"


def copy_fixture(name, tmp_path):
    return Path(shutil.copytree(FIXTURES / name, tmp_path / "repo"))


@pytest.mark.parametrize("name", ["nan", "infinity", "negative-infinity", "bom"])
def test_package_json_rejects_non_json_syntax(tmp_path, name):
    repo = copy_fixture(name, tmp_path)
    result = run_cli(
        [
            "lint",
            str(repo),
            "--no-custom-rules",
            "--rule",
            "openclaw-package-valid",
            "--format",
            "json",
        ]
    )
    assert result.returncode == 1, result.stderr
    violations = json.loads(result.stdout)["violations"]
    assert len(violations) == 1
    assert violations[0]["rule_id"] == "openclaw-package-valid"
    assert violations[0]["file_path"] == "package.json"
    assert "Cannot parse package.json" in violations[0]["message"]
    # Invalid package syntax must not establish native ownership by itself.
    assert not declares_extensions(repo / "package.json")


def test_manifest_json5_preserves_bom_and_non_finite_numbers(tmp_path):
    repo = copy_fixture("valid-json5", tmp_path)
    result = run_cli(
        [
            "lint",
            str(repo),
            "--no-custom-rules",
            "--rule",
            "openclaw-package-valid",
            "--rule",
            "openclaw-manifest-valid",
            "--format",
            "json",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["violations"] == []
    assert declares_extensions(repo / "package.json")
