"""Core-owned writes must be visible without caller-managed cache resets."""

import json
from pathlib import Path

import pytest

from skillsaw.blocks import BodyContent, ContentFile, FrontmatterField, SkillBlock
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_text
from tests.cli_runner import run_cli
from tests.test_autofix import copy_fixture

RULE = "content-unlinked-internal-reference"
FIXTURES = [
    ("autofix/info-hidden", "SKILL.md"),
    ("autofix/unlinked-ref-already-linked", "CLAUDE.md"),
]


def make_linter(repo):
    return Linter(RepositoryContext(repo), rule_ids={RULE}, no_custom_rules=True, no_plugins=True)


@pytest.mark.parametrize("body_first", [True, False], ids=["body-first", "frontmatter-first"])
def test_consecutive_block_writes_preserve_body_and_frontmatter(tmp_path, body_first):
    repo = copy_fixture("autofix/info-hidden", tmp_path)
    path = repo / "SKILL.md"
    tree = RepositoryContext(repo).lint_tree
    block = tree.find(SkillBlock)[0]
    original_fields = tree.find(FrontmatterField)
    body = tree.find(BodyContent)[0]
    original_doc = body.markdown
    original_body = body.read_body(strip_code_blocks=False)
    assert body.markdown is original_doc
    assert tree.find(BodyContent)[0] is body

    new_body = "# Updated review\n\nRead [the guide](references/guide.md) before reviewing.\n"
    new_fm = (
        "name: info-hidden\ndescription: Review the updated contribution guide.\nversion: 1.0.0\n"
    )
    if body_first:
        body.write_body(new_body)
        assert block.body_text == new_body
        block.write_frontmatter_text(new_fm)
    else:
        block.write_frontmatter_text(new_fm)
        assert block.field_value("version") == "1.0.0"
        # A caller may still hold the body obtained before adding a field.
        body.write_body(new_body)

    expected = "---\n" + new_fm + "---\n" + new_body
    assert path.read_text() == expected
    assert read_text(path) == expected
    assert block.read_frontmatter_text() == new_fm
    assert block.body_text == new_body
    assert block.field_value("description") == "Review the updated contribution guide."
    assert block.field_value("version") == "1.0.0"
    assert block.key_line("version") == 4
    assert {f.name for f in tree.find(FrontmatterField)} == {"name", "description", "version"}
    current_body = tree.find(BodyContent)[0]
    assert any(child is current_body for child in block.children)
    assert all(child is not body for child in block.children)
    assert current_body.parent is block
    assert current_body.read_body(strip_code_blocks=False) == new_body
    assert current_body.file_line(1) == 6
    assert current_body.markdown.body == new_body
    assert [(link.href, link.file_line) for link in current_body.markdown.links()] == [
        ("references/guide.md", 8)
    ]
    assert current_body.markdown is current_body.markdown
    assert original_doc.body == original_body
    assert {f.name for f in original_fields} == {"name", "description"}


def test_empty_body_write_removes_cached_body_child(tmp_path):
    repo = copy_fixture("autofix/info-hidden", tmp_path)
    tree = RepositoryContext(repo).lint_tree
    block = tree.find(SkillBlock)[0]
    body = tree.find(BodyContent)[0]

    body.write_body("")

    assert block.body_text == ""
    assert tree.find(BodyContent) == []
    assert not any(child is body for child in block.children)
    block.write_frontmatter_text("name: info-hidden\ndescription: Review contribution changes.\n")
    assert (repo / "SKILL.md").read_text() == (
        "---\nname: info-hidden\ndescription: Review contribution changes.\n---\n"
    )
    assert tree.find(BodyContent) == []


@pytest.mark.parametrize("preloaded", [False, True])
def test_file_body_write_refreshes_reads_and_cached_lookups(tmp_path, preloaded):
    repo = copy_fixture("autofix/unlinked-ref-already-linked", tmp_path)
    path = repo / "CLAUDE.md"
    original = read_text(path)
    block = ContentFile(path=path, body=original if preloaded else None)
    tree = LintTarget(path=repo, children=[block])
    tree.set_parents()
    doc = block.markdown
    assert block.markdown is doc

    def mentions_tldr(node):
        return "TLDR" in node.read_body(strip_code_blocks=False)

    assert tree.find_filtered(ContentFile, "tldr", mentions_tldr) == [block]
    updated = "# Review guide\n\nRead [the guide](docs/guide.md) before proposing changes.\n"
    block.write_body(updated)

    assert path.read_text() == updated
    assert read_text(path) == updated
    assert block.read_body(strip_code_blocks=False) == updated
    assert block.markdown.body == updated
    assert block.markdown is not doc
    assert tree.find_filtered(ContentFile, "tldr", mentions_tldr) == []
    assert doc.body == original


@pytest.mark.parametrize("writer", ["file", "body", "frontmatter"])
def test_failed_block_write_preserves_cached_state(tmp_path, monkeypatch, writer):
    repo = copy_fixture("autofix/info-hidden", tmp_path)
    path = repo / "SKILL.md"
    tree = RepositoryContext(repo).lint_tree
    block = tree.find(SkillBlock)[0]
    body = tree.find(BodyContent)[0]
    original = read_text(path)
    doc = body.markdown
    fields = tree.find(FrontmatterField)
    description = block.field_value("description")
    plain = ContentFile(path=path, body=original)

    def denied(*_args, **_kwargs):
        raise PermissionError("fixture write denied")

    monkeypatch.setattr(Path, "write_text", denied)
    with pytest.raises(PermissionError, match="fixture write denied"):
        if writer == "file":
            plain.write_body("Updated body.\n")
        elif writer == "body":
            body.write_body("Updated body.\n")
        else:
            block.write_frontmatter_text("name: info-hidden\ndescription: Updated.\n")

    assert path.read_text() == original
    assert read_text(path) == original
    assert tree.find(BodyContent)[0] is body
    assert body.markdown is doc
    assert tree.find(FrontmatterField) == fields
    assert block.field_value("description") == description
    assert plain.read_body(strip_code_blocks=False) == original


@pytest.mark.parametrize("fixture,filename", FIXTURES)
@pytest.mark.parametrize("max_passes", [1, 20])
def test_final_fix_pass_refreshes_same_and_fresh_contexts(tmp_path, fixture, filename, max_passes):
    repo = copy_fixture(fixture, tmp_path)
    path = repo / filename
    linter = make_linter(repo)
    before = path.read_bytes()
    assert [v.file_path for v in linter.run()] == [path]
    tree = linter.context.lint_tree
    assert [v.file_path for v in linter.run()] == [path]
    assert linter.context.lint_tree is tree, "unchanged runs should reuse the tree"

    applied, suggested = linter.fix_and_apply(max_passes=max_passes)

    assert [fix.file_path for fix in applied] == [path]
    assert suggested == []
    after = path.read_bytes()
    assert after != before
    assert len(after.splitlines()) == len(before.splitlines())
    assert linter.run() == []
    assert make_linter(repo).run() == []
    assert linter.fix_and_apply(max_passes=max_passes) == ([], [])
    assert path.read_bytes() == after


@pytest.mark.parametrize("mode", ["dry-run", "failed-write"])
def test_unapplied_fix_preserves_disk_and_cached_tree(tmp_path, monkeypatch, mode):
    repo = copy_fixture("autofix/info-hidden", tmp_path)
    path = repo / "SKILL.md"
    linter = make_linter(repo)
    before = read_text(path)
    assert [v.file_path for v in linter.run()] == [path]
    tree = linter.context.lint_tree

    def denied(*_args, **_kwargs):
        raise PermissionError("fixture write denied")

    if mode == "failed-write":
        monkeypatch.setattr("skillsaw.linter.write_text_preserving", denied)
    applied, suggested = linter.fix_and_apply(max_passes=1, dry_run=mode == "dry-run")

    assert suggested == []
    if mode == "failed-write":
        assert applied == []
        assert len(linter.fix_failures) == 1
        assert "fixture write denied" in linter.fix_failures[0][1]
    else:
        assert len(applied) == 1  # A dry run returns the planned fix without applying it.
        assert linter.fix_failures == []
    assert path.read_text() == before
    assert read_text(path) == before
    assert linter.context.lint_tree is tree
    assert [v.file_path for v in linter.run()] == [path]


@pytest.mark.integration
@pytest.mark.parametrize("fixture,filename", FIXTURES)
def test_cli_fix_converges_on_static_fixture(tmp_path, fixture, filename):
    repo = copy_fixture(fixture, tmp_path)
    path = repo / filename
    before = path.read_bytes()
    options = [str(repo), "--rule", RULE, "--no-custom-rules", "--no-plugins"]
    lint_args = ["lint", *options, "--format", "json", "--fail-on", "info"]
    first = run_cli(lint_args)
    report = json.loads(first.stdout)
    assert first.returncode == 1
    assert [(v["rule_id"], v["file_path"]) for v in report["violations"]] == [(RULE, filename)]

    fixed = run_cli(["fix", *options])
    assert fixed.returncode == 0, fixed.stderr
    after = path.read_bytes()
    assert len(after.splitlines()) == len(before.splitlines())
    assert sum(a != b for a, b in zip(before.splitlines(), after.splitlines())) == 1
    clean = run_cli(lint_args)
    assert clean.returncode == 0, clean.stderr
    assert json.loads(clean.stdout)["violations"] == []
    repeated = run_cli(["fix", *options])
    assert repeated.returncode == 0, repeated.stderr
    assert path.read_bytes() == after
