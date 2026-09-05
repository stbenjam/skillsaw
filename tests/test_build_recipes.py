"""Execute the example recipe with a harmless CLI stand-in."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("fail", [False, True], ids=["success", "init-fails"])
def test_generate_example_preserves_temp_root_and_cleans_its_workspace(tmp_path, fail):
    repo = tmp_path / "project"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    bin_dir = repo / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/fixtures/build-recipes/skillsaw", bin_dir / "skillsaw")
    (bin_dir / "skillsaw").chmod(0o755)
    stamp = repo / "venv" / ".skillsaw-extras-dev-docs"
    stamp.touch()
    temp_root = tmp_path / "scratch root"
    temp_root.mkdir()
    sentinel = temp_root / "keep.txt"
    sentinel.write_text("unrelated scratch data")
    generated = repo / ".skillsaw.yaml.example"
    generated.write_text("previous config\n")
    record = repo / "record.txt"
    env = dict(os.environ, TMPDIR=str(temp_root), RECIPE_RECORD=str(record))
    env["RECIPE_FAIL"] = "yes" if fail else ""

    # A real make process is essential: the regression is an exported Make
    # variable leaking into later recipe shells, not Python state.
    result = subprocess.run(
        [
            "make",
            "-f",
            str(ROOT / "Makefile"),
            "-f",
            str(ROOT / "tests/fixtures/build-recipes/after.mk"),
            "generate-example",
            "after-generation",
            "VENV=venv",
        ],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == (2 if fail else 0), result.stdout + result.stderr
    inherited_temp, workspace = record.read_text().splitlines()
    assert inherited_temp == str(temp_root)
    assert Path(workspace).parent == temp_root
    assert not Path(workspace).exists()
    assert sentinel.read_text() == "unrelated scratch data"
    assert generated.read_text() == ("previous config\n" if fail else "generated config\n")
    if not fail:
        assert (repo / "after.txt").read_text().strip() == str(temp_root)
