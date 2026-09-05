"""Embedded YAML writes refresh owned caches after a successful write."""

from copy import deepcopy
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from skillsaw.blocks import CodeRabbitContentBlock, PromptfooPromptBlock
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.utils import read_text, read_yaml_commented
from tests.test_integration import copy_fixture

CASES = [
    ("coderabbit", CodeRabbitContentBlock, ".coderabbit.yaml"),
    ("promptfoo", PromptfooPromptBlock, "promptfooconfig.yaml"),
]
RULE = "content-weak-language"


def _linter(repo):
    return Linter(RepositoryContext(repo), rule_ids={RULE}, no_custom_rules=True, no_plugins=True)


def _replace_instruction(data, host, index, value):
    if host == "coderabbit":
        data["reviews"]["path_instructions"][index]["instructions"] = value
    else:
        data["prompts"][index] = value


@pytest.mark.parametrize("host,block_cls,filename", CASES)
@pytest.mark.parametrize("updated", ["Review [the checklist](docs/checklist.md).", ""])
def test_embedded_write_refreshes_reads_markdown_and_cached_tree(
    tmp_path, host, block_cls, filename, updated
):
    repo = copy_fixture(f"yaml-writers/{host}", tmp_path)
    path = repo / filename
    linter = _linter(repo)
    initial = linter.run()
    assert len(initial) == 1 and "Try to" in initial[0].message
    tree = linter.context.lint_tree
    blocks = tree.find(block_cls)
    target, sibling = blocks
    sibling_body = sibling.read_body(strip_code_blocks=False)
    old_doc = target.markdown
    old_data, error, _ = read_yaml_commented(path)
    assert error is None
    before = path.read_text()
    assert read_text(path) == before
    assert target.markdown is old_doc

    def weak(block):
        return "Try to" in block.read_body(strip_code_blocks=False)

    assert tree.find_filtered(block_cls, "weak-canary", weak) == [target]
    target.write_body(updated)

    expected = deepcopy(old_data)
    _replace_instruction(expected, host, 0, updated)
    disk = path.read_text()
    assert disk != before
    assert read_text(path) == disk
    assert YAML(typ="safe").load(disk) == expected
    new_data, error, _ = read_yaml_commented(path)
    assert error is None and new_data == expected and new_data is not old_data
    assert "# Keep this sibling" in disk
    assert target.read_body(strip_code_blocks=False) == updated
    assert target.markdown.body == updated
    assert target.markdown is not old_doc
    assert tree.find_filtered(block_cls, "weak-canary", weak) == []
    assert sibling.read_body(strip_code_blocks=False) == sibling_body
    assert linter.context.lint_tree is tree
    assert linter.run() == []
    assert _linter(repo).run() == []
    target.write_body(updated)
    assert path.read_text() == disk


@pytest.mark.parametrize("host,block_cls,filename", CASES)
def test_consecutive_sibling_writes_preserve_the_latest_yaml(tmp_path, host, block_cls, filename):
    repo = copy_fixture(f"yaml-writers/{host}", tmp_path)
    context = RepositoryContext(repo)
    first, second = context.lint_tree.find(block_cls)
    path = repo / filename
    before, error, _ = read_yaml_commented(path)
    assert error is None
    first_body = "Review the release checklist.\nRecord its outcome."
    second_body = "Confirm the focused tests pass."

    first.write_body(first_body)
    second.write_body(second_body)

    expected = deepcopy(before)
    _replace_instruction(expected, host, 0, first_body)
    _replace_instruction(expected, host, 1, second_body)
    assert YAML(typ="safe").load(path.read_text()) == expected
    assert read_yaml_commented(path)[0] == expected
    assert [
        block.read_body(strip_code_blocks=False) for block in context.lint_tree.find(block_cls)
    ] == [first_body, second_body]
    assert [
        block.read_body(strip_code_blocks=False)
        for block in RepositoryContext(repo).lint_tree.find(block_cls)
    ] == [first_body, second_body]


@pytest.mark.parametrize("host,block_cls,filename", CASES)
def test_failed_embedded_write_preserves_disk_and_cached_state(
    tmp_path, monkeypatch, host, block_cls, filename
):
    repo = copy_fixture(f"yaml-writers/{host}", tmp_path)
    tree = RepositoryContext(repo).lint_tree
    block = tree.find(block_cls)[0]
    path = repo / filename
    before = path.read_text()
    raw = read_text(path)
    parsed = read_yaml_commented(path)[0]
    body = block.read_body(strip_code_blocks=False)
    doc = block.markdown
    write_text = Path.write_text

    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("fixture write denied")
        return write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", denied)
    # Keep the established exception behavior of each writer.
    if host == "promptfoo":
        with pytest.raises(PermissionError, match="fixture write denied"):
            block.write_body("Updated instructions.")
    else:
        block.write_body("Updated instructions.")

    assert path.read_text() == before
    assert read_text(path) is raw
    assert read_yaml_commented(path)[0] is parsed
    assert block.read_body(strip_code_blocks=False) == body
    assert block.markdown is doc
    assert tree.find(block_cls)[0] is block


@pytest.mark.parametrize(
    "host,block_cls,filename,yaml_path",
    [
        (*CASES[0], "reviews.path_instructions[99].instructions"),
        (*CASES[1], "prompts[99]"),
        (*CASES[1], "prompts[-1]"),
        (*CASES[1], "prompts[invalid]"),
    ],
)
def test_missing_embedded_target_does_not_write_or_publish_a_body(
    tmp_path, monkeypatch, host, block_cls, filename, yaml_path
):
    repo = copy_fixture(f"yaml-writers/{host}", tmp_path)
    tree = RepositoryContext(repo).lint_tree
    block = tree.find(block_cls)[0]
    block.yaml_path = yaml_path
    path = repo / filename
    before = path.read_text()
    raw = read_text(path)
    parsed = read_yaml_commented(path)[0]
    body = block.read_body(strip_code_blocks=False)
    doc = block.markdown
    writes = []
    write_text = Path.write_text

    def observe(self, *args, **kwargs):
        writes.append(self)
        return write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", observe)
    block.write_body("Updated instructions.")

    assert writes == []
    assert path.read_text() == before
    assert read_text(path) is raw
    assert read_yaml_commented(path)[0] is parsed
    assert block.read_body(strip_code_blocks=False) == body
    assert block.markdown is doc
