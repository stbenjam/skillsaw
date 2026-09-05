"""Execute the Action's installer selection without installing packages."""

import os
import subprocess
from pathlib import Path

import pytest

from skillsaw import __version__
from skillsaw.utils import read_yaml_commented

REPO_ROOT = Path(__file__).parent.parent

# Record arguments and plugin requirements before the step removes its tempfile.
# A shell function keeps every pip invocation inside this harmless recorder.
_PIP_RECORDER = r"""
pip() {
  printf '%s\0' "$@" >> "$PIP_RECORD"
  printf '\0' >> "$PIP_RECORD"
  if [ "$3" = '-r' ]; then
    cat "$4" > "$PLUGIN_RECORD"
  fi
  return "$PIP_EXIT_CODE"
}
"""


def _run_install(tmp_path, *, version=None, checkout=True, plugins="", pip_exit=0):
    action, error, _ = read_yaml_commented(REPO_ROOT / "action.yml")
    assert error is None
    step = next(s for s in action["runs"]["steps"] if s["name"] == "Install skillsaw")
    action_path = tmp_path / "action checkout"
    action_path.mkdir()
    if checkout:
        (action_path / "pyproject.toml").write_text('[project]\nname = "skillsaw"\n')
    record = tmp_path / "pip-arguments"
    plugin_record = tmp_path / "plugin-requirements"
    env = {
        **os.environ,
        "TMPDIR": str(tmp_path),
        "ACTION_PATH": str(action_path),
        "SKILLSAW_VERSION": (
            action["inputs"]["version"]["default"] if version is None else version
        ),
        "SKILLSAW_PLUGINS": plugins,
        "PIP_RECORD": str(record),
        "PLUGIN_RECORD": str(plugin_record),
        "PIP_EXIT_CODE": str(pip_exit),
    }
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            _PIP_RECORDER + step["run"],
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    calls = (
        [call.decode().split("\0") for call in record.read_bytes().split(b"\0\0")[:-1]]
        if record.exists()
        else []
    )
    return result, calls, action_path, plugin_record


def test_default_installs_action_checkout(tmp_path):
    result, calls, action_path, _ = _run_install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert calls == [["install", "-q", str(action_path)]]


@pytest.mark.parametrize("version", ["0.19.0", __version__, "0.21.0rc1"])
@pytest.mark.parametrize("checkout", [True, False])
def test_explicit_version_installs_requested_release(tmp_path, version, checkout):
    result, calls, _, _ = _run_install(tmp_path, version=version, checkout=checkout)
    assert result.returncode == 0, result.stderr
    assert calls == [["install", "-q", f"skillsaw=={version}"]]


def test_default_without_checkout_fails_clearly(tmp_path):
    result, calls, _, _ = _run_install(tmp_path, checkout=False)
    assert result.returncode != 0
    assert "pyproject.toml" in result.stderr
    assert "version" in result.stderr
    assert calls == []


@pytest.mark.parametrize("version", [None, "0.19.0"])
def test_plugins_keep_separate_requirements_install(tmp_path, version):
    plugins = "example-rule-plugin==1.2.3\nsecond-rule-plugin>=2"
    result, calls, action_path, plugin_record = _run_install(
        tmp_path, version=version, plugins=plugins
    )
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2
    assert calls[0] == [
        "install",
        "-q",
        str(action_path) if version is None else f"skillsaw=={version}",
    ]
    assert calls[1][:3] == ["install", "-q", "-r"]
    assert len(calls[1]) == 4
    assert plugin_record.read_text() == plugins + "\n"
    assert not Path(calls[1][3]).exists(), "successful install must remove its tempfile"


def test_failed_package_install_stops_before_plugins(tmp_path):
    result, calls, _, plugin_record = _run_install(
        tmp_path, version="0.19.0", plugins="example-rule-plugin==1.2.3", pip_exit=17
    )
    assert result.returncode == 17
    assert calls == [["install", "-q", "skillsaw==0.19.0"]]
    assert not plugin_record.exists()
