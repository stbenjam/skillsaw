"""Pi project paths normalize independently of literal manifest paths."""

import json
from pathlib import Path, PureWindowsPath
import shutil
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from skillsaw.blocks.pi import PiExtensionNode, PiPromptBlock
from skillsaw.context import RepositoryContext
from skillsaw.discovery.pi import local_path
from skillsaw.discovery import pi
from tests.cli_runner import run_cli


def copy_fixture(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(Path(__file__).parent / "fixtures/pi/path-normalization", root)
    return root


def lint_paths(root):
    result = run_cli(
        ["lint", str(root), "--no-custom-rules", "--rule", "pi-resource-paths", "--format", "json"]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)["violations"]


def test_project_whitespace_paths_and_literal_manifest_paths(tmp_path):
    root = copy_fixture(tmp_path)
    context = RepositoryContext(root)
    assert {
        block.path.relative_to(root).as_posix() for block in context.lint_tree.find(PiPromptBlock)
    } == {
        "templates/review.md",
        "string-package/prompts/string.md",
        "object-package/prompts/object.md",
        " templates/literal.md ",
    }
    assert {block.path for block in context.lint_tree.find(PiExtensionNode)} == {
        root / "extensions/direct.ts"
    }
    assert lint_paths(root) == []


def test_contained_file_urls_load_prompts_and_local_packages(tmp_path):
    root = copy_fixture(tmp_path)
    prompt = root / "templates/review notes.md"
    (root / "templates/review.md").rename(prompt)
    settings = {
        "prompts": [prompt.as_uri()],
        "packages": [
            (root / "string-package").as_uri(),
            {"source": (root / "object-package").as_uri()},
            (root / "extensions/direct.ts").as_uri(),
        ],
    }
    (root / ".pi/settings.json").write_text(json.dumps(settings))
    assert "%20" in settings["prompts"][0]
    context = RepositoryContext(root)
    prompts = {block.path for block in context.lint_tree.find(PiPromptBlock)}
    assert prompts == {
        prompt,
        root / "string-package/prompts/string.md",
        root / "object-package/prompts/object.md",
        root / " templates/literal.md ",
    }
    assert {block.path for block in context.lint_tree.find(PiExtensionNode)} == {
        root / "extensions/direct.ts"
    }
    assert lint_paths(root) == []


@pytest.mark.parametrize(
    "entry",
    [
        " ~/private.md ",
        " https://example.com/repo ",
        " npm:example-package ",
        " git:github.com/example/repo ",
        " ../../outside.md ",
        "file:///etc/passwd",
        "file://example.com/repo/resource.md",
        "file:///tmp/%2fetc/passwd",
        "file:///tmp/%00resource.md",
    ],
)
def test_normalized_paths_keep_local_boundary(tmp_path, entry):
    root = copy_fixture(tmp_path)
    assert local_path(root / ".pi", entry, root, settings=True) is None


def test_file_url_symlink_escape_is_not_loaded(tmp_path):
    root = copy_fixture(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("Read the external private notes.\n")
    link = root / "templates/escape.md"
    link.symlink_to(outside)
    (root / ".pi/settings.json").write_text(json.dumps({"prompts": [link.as_uri()]}))
    assert local_path(root / ".pi", link.as_uri(), root, settings=True) is None
    context = RepositoryContext(root)
    assert link not in {block.path for block in context.lint_tree.find(PiPromptBlock)}
    assert lint_paths(root) == []


@pytest.mark.parametrize(
    "suffix", ["templates%2freview.md", "templates/review%ZZ.md", "templates/review%.md"]
)
def test_invalid_file_url_encoding_is_rejected_inside_checkout(tmp_path, suffix):
    root = copy_fixture(tmp_path)
    entry = root.as_uri() + "/" + suffix
    assert local_path(root / ".pi", entry, root, settings=True) is None


@pytest.mark.parametrize("relative", ["prompts/review notes.md", "package", "extensions/direct.ts"])
def test_windows_file_url_uses_drive_absolute_path(monkeypatch, relative):
    import ntpath

    root = PureWindowsPath("C:/repo")
    target = root / relative
    checked = []

    def contained(path, boundary):
        checked.append((path, boundary))
        return path

    monkeypatch.setattr(pi, "os", SimpleNamespace(name="nt", path=ntpath))
    monkeypatch.setattr(pi, "Path", PureWindowsPath)
    monkeypatch.setattr(pi, "contained_resolve", contained)

    uri = "file:///C:/repo/" + quote(relative)
    assert local_path(root / ".pi", uri, root, settings=True) == target
    assert checked == [(target, root)]


@pytest.mark.parametrize(
    "entry",
    [
        "file:///repo/prompt.md",
        "file:////server/share/prompt.md",
        "file:///C:/repo/prompts%5Creview.md",
        "file:///C:/repo/prompts%5creview.md",
    ],
)
def test_windows_file_urls_reject_invalid_roots_and_encoded_backslashes(monkeypatch, entry):
    import ntpath

    root = PureWindowsPath("C:/repo")
    monkeypatch.setattr(pi, "os", SimpleNamespace(name="nt", path=ntpath))
    monkeypatch.setattr(pi, "Path", PureWindowsPath)

    def unexpected_resolve(*args):
        pytest.fail("Invalid file URL reached filesystem resolution")

    monkeypatch.setattr(pi, "contained_resolve", unexpected_resolve)
    assert local_path(root / ".pi", entry, root, settings=True) is None
