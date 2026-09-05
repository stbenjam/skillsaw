"""Execute the example recipe with a harmless CLI stand-in."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "destination,fail",
    [
        ("regular", False),
        ("file-symlink", False),
        ("directory", False),
        ("directory-symlink", False),
        ("regular", True),
    ],
)
def test_generate_example_preserves_temp_root_and_cleans_its_workspace(tmp_path, fail, destination):
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
    is_directory = destination in {"directory", "directory-symlink"}
    target = repo / "local-target"
    if is_directory:
        directory = target if destination == "directory-symlink" else generated
        directory.mkdir()
        (directory / "keep.txt").write_text("existing directory data\n")
        if destination == "directory-symlink":
            generated.symlink_to(target.name, target_is_directory=True)
    elif destination == "file-symlink":
        target.write_text("previous config\n")
        generated.symlink_to(target.name)
    else:
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
            "VENV_EXTRAS=dev,docs",
        ],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == (2 if fail or is_directory else 0), result.stdout + result.stderr
    inherited_temp, workspace = record.read_text().splitlines()
    assert inherited_temp == str(temp_root)
    assert Path(workspace).parent == temp_root
    assert not Path(workspace).exists()
    assert sentinel.read_text() == "unrelated scratch data"
    if is_directory:
        assert generated.is_dir()
        assert generated.is_symlink() == (destination == "directory-symlink")
        assert sorted(path.name for path in generated.iterdir()) == ["keep.txt"]
        assert (generated / "keep.txt").read_text() == "existing directory data\n"
        if not fail:
            assert ".skillsaw.yaml.example is a directory" in result.stderr
    else:
        assert generated.read_text() == ("previous config\n" if fail else "generated config\n")
        if destination == "file-symlink":
            assert target.read_text() == "previous config\n"
            assert generated.is_symlink() == fail
    if not fail and not is_directory:
        assert (repo / "after.txt").read_text().strip() == str(temp_root)
