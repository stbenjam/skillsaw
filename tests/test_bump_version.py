"""Regression tests for scripts/bump-version.sh.

The script's inline python must reach the interpreter with quotes,
backticks, and ``$`` intact: shell-active characters in a double-quoted
inline program are word-split or command-substituted, leaving pin rewrites
silently dead at exit 0. These tests run the script end-to-end against a
tmp copy of every pinned file so a rewrite cannot go quietly inert.
"""

import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bump-version.sh"

OLD = "1.2.3"
NEW = "1.3.0"


def _make_repo(tmp_path: Path) -> Path:
    """Lay out a minimal repo copy carrying every pin pattern the script
    rewrites, each seeded with OLD."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "bump-version.sh")

    (repo / "src" / "skillsaw").mkdir(parents=True)
    (repo / "docs").mkdir()
    plugin = repo / "examples" / "plugins" / "skillsaw-example-plugin"
    plugin.mkdir(parents=True)

    (repo / "pyproject.toml").write_text(f'[project]\nname = "skillsaw"\nversion = "{OLD}"\n')
    (repo / "src" / "skillsaw" / "__init__.py").write_text(f'__version__ = "{OLD}"\n')
    (repo / "action.yml").write_text(
        "inputs:\n  version:\n    description: Version to install\n" f"    default: '{OLD}'\n"
    )
    (repo / "docs" / "ci.md").write_text(
        f"Install with `pip install skillsaw=={OLD}`.\n\n"
        f"| `version` | Specific skillsaw version to install | `{OLD}` |\n"
    )
    (repo / "docs" / "pre-commit.md").write_text(f"    rev: v{OLD}\n")
    # The floor moves; prose recording the release that introduced an API
    # must not.
    (repo / "docs" / "plugins.md").write_text(
        f'Declare `"skillsaw>={OLD}"` in your plugin.\n\n'
        f"The `provenance_scope` attribute requires skillsaw {OLD} or newer.\n"
    )
    (plugin / "pyproject.toml").write_text(f'dependencies = ["skillsaw>={OLD}"]\n')
    return repo


def _run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "bump-version.sh"), NEW],
        capture_output=True,
        text=True,
    )


def test_bump_moves_every_pin_site_together(tmp_path):
    repo = _make_repo(tmp_path)
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    # A quoting break surfaces as bash `command not found` noise on stderr
    # while the script still exits 0 — any stderr is a regression.
    assert result.stderr == "", result.stderr

    assert f'version = "{NEW}"' in (repo / "pyproject.toml").read_text()
    assert f'__version__ = "{NEW}"' in (repo / "src" / "skillsaw" / "__init__.py").read_text()
    assert f"default: '{NEW}'" in (repo / "action.yml").read_text()

    ci = (repo / "docs" / "ci.md").read_text()
    assert f"skillsaw=={NEW}" in ci
    # The action-input table row is what test_release_metadata asserts
    # against the project version; its pattern carries backticks, the
    # characters most easily lost to the shell.
    assert f"| `version` | Specific skillsaw version to install | `{NEW}` |" in ci

    assert f"rev: v{NEW}" in (repo / "docs" / "pre-commit.md").read_text()

    plugins_doc = (repo / "docs" / "plugins.md").read_text()
    assert f"skillsaw>={NEW}" in plugins_doc
    assert (
        f"requires skillsaw {OLD} or newer" in plugins_doc
    ), "API-introduction prose must keep the release it records"

    plugin_pyproject = (
        repo / "examples" / "plugins" / "skillsaw-example-plugin" / "pyproject.toml"
    ).read_text()
    assert f"skillsaw>={NEW}" in plugin_pyproject

    assert OLD not in ci
    for leftover in ("pyproject.toml", "action.yml"):
        assert OLD not in (repo / leftover).read_text()


def test_bump_defaults_to_patch_increment(tmp_path):
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "bump-version.sh")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert 'version = "1.2.4"' in (repo / "pyproject.toml").read_text()
    assert '__version__ = "1.2.4"' in (repo / "src" / "skillsaw" / "__init__.py").read_text()


def test_bump_skips_missing_docs(tmp_path):
    """Docs get reorganized; a missing pinned doc is not an error."""
    repo = _make_repo(tmp_path)
    (repo / "docs" / "pre-commit.md").unlink()
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert f'version = "{NEW}"' in (repo / "pyproject.toml").read_text()
