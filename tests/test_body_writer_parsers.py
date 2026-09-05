"""Direct body writes must keep the owning host's frontmatter boundary."""

from pathlib import Path

import pytest

from skillsaw.blocks import (
    BodyContent,
    CursorRuleBlock,
    DevinRuleBlock,
    DevinSkillBlock,
    GrokAgentBlock,
    SkillBlock,
)
from skillsaw.context import RepositoryContext
from skillsaw.utils import read_text
from tests.test_autofix import copy_fixture

BODY = "# Review metadata\n\nRead [the guide](https://example.com/guide) before recording the result.\n"
NEW_BODY = "# Review configuration\n\nRead [the checklist](https://example.com/checklist) before recording the result.\n"
CASES = [
    (
        SkillBlock,
        ".agents/skills/portable/SKILL.md",
        "---\nname: portable\ndescription: Review local metadata. Use when checking configuration fields.\n---\n",
    ),
    (DevinSkillBlock, ".devin/skills/empty-review/SKILL.md", "---\n---\n"),
    (DevinRuleBlock, ".windsurf/rules/manual.md", "---\n# Optional activation\n---\n"),
    (CursorRuleBlock, ".cursor/rules/review.mdc", "---\nglobs: **/*.py\n---\n"),
    (
        GrokAgentBlock,
        ".grok/agents/reviewer.md",
        "  \n---name: reviewer\ndescription: Review local metadata. Use when inspecting configuration fields.\n--- closing marker\n",
    ),
]


@pytest.mark.parametrize("block_type,relative,prefix", CASES)
def test_body_write_uses_parent_dialect_and_preserves_other_files(
    tmp_path, block_type, relative, prefix
):
    repo = copy_fixture("regression/body-writer-parsers", tmp_path)
    path = repo / relative
    context = RepositoryContext(repo)
    tree = context.lint_tree
    block = next(block for block in tree.find(block_type) if block.path == path)
    body = block.find(BodyContent)[0]
    doc = body.markdown
    others = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and p != path}
    before = path.read_bytes()
    assert path.read_text() == prefix + BODY
    assert block.body_text == BODY
    assert read_text(path) == prefix + BODY

    body.write_body(NEW_BODY)

    expected = prefix + NEW_BODY
    assert path.read_text() == expected
    assert read_text(path) == expected
    assert len(path.read_bytes().splitlines()) == len(before.splitlines())
    assert block.body_text == NEW_BODY
    current = next(child for child in tree.find(BodyContent) if child.path == path)
    assert current.parent is block
    assert current.markdown.body == NEW_BODY
    assert current.markdown.links()[0].file_line == prefix.count("\n") + 3
    fresh = next(
        block for block in RepositoryContext(repo).lint_tree.find(block_type) if block.path == path
    )
    assert fresh.body_text == NEW_BODY
    current.write_body(NEW_BODY)
    assert path.read_text() == expected
    assert all(p.read_bytes() == data for p, data in others.items())
    assert doc.body == BODY


@pytest.mark.parametrize(
    "block_type", [SkillBlock, DevinSkillBlock, DevinRuleBlock, GrokAgentBlock]
)
def test_body_write_refuses_malformed_parent_without_mutating_state(tmp_path, block_type):
    path = tmp_path / "context.md"
    original = "---\nname: [unterminated\n---\nReview local metadata.\n"
    path.write_text(original)
    block = block_type(path=path)
    body = block.find(BodyContent)[0]
    doc = body.markdown
    fields = list(block.children)
    assert block.frontmatter_error is not None

    with pytest.raises(ValueError, match="frontmatter is malformed"):
        body.write_body(NEW_BODY)

    assert path.read_text() == original
    assert read_text(path) == original
    assert all(current is previous for current, previous in zip(block.children, fields))
    assert body.markdown is doc
    assert body.read_body(strip_code_blocks=False) == original


@pytest.mark.parametrize(
    "new_body", ["Updated metadata.", "Updated metadata.\nReview the next field."]
)
def test_grok_eof_body_changes_must_preserve_the_parser_boundary(tmp_path, new_body):
    path = tmp_path / "reviewer.md"
    prefix = "---name: reviewer\n---"
    original = prefix + "Review metadata."
    path.write_text(original)
    block = GrokAgentBlock(path=path)
    body = block.find(BodyContent)[0]
    doc = body.markdown
    assert body.read_body(strip_code_blocks=False) == "Review metadata."

    if "\n" in new_body:
        with pytest.raises(ValueError, match="frontmatter boundary"):
            body.write_body(new_body)
        assert path.read_text() == original
        assert read_text(path) == original
        assert block.find(BodyContent)[0] is body
        assert body.markdown is doc
        assert block.body_text == "Review metadata."
    else:
        body.write_body(new_body)
        assert path.read_text() == prefix + new_body
        assert block.body_text == new_body
        assert GrokAgentBlock(path=path).body_text == new_body
        block.find(BodyContent)[0].write_body(new_body)
        assert path.read_text() == prefix + new_body


def test_body_write_does_not_turn_new_prose_into_frontmatter(tmp_path):
    path = tmp_path / "SKILL.md"
    original = "Review local metadata.\n"
    path.write_text(original)
    block = SkillBlock(path=path)
    body = block.find(BodyContent)[0]

    with pytest.raises(ValueError, match="frontmatter boundary"):
        body.write_body("---\nname: new-review\n---\nNew prose.\n")

    assert path.read_text() == original
    assert block.body_text == original
    assert block.find(BodyContent)[0] is body


def test_failed_native_body_write_preserves_cache_state(tmp_path, monkeypatch):
    path = tmp_path / "SKILL.md"
    original = "---\n---\n" + BODY
    path.write_text(original)
    block = DevinSkillBlock(path=path)
    body = block.find(BodyContent)[0]
    doc = body.markdown

    def denied(*args, **kwargs):
        raise PermissionError("write denied by test")

    monkeypatch.setattr("skillsaw.blocks.frontmatter.write_text_preserving", denied)
    with pytest.raises(PermissionError, match="write denied by test"):
        body.write_body(NEW_BODY)

    assert path.read_text() == original
    assert read_text(path) == original
    assert block.body_text == BODY
    assert block.find(BodyContent)[0] is body
    assert body.markdown is doc


@pytest.mark.parametrize("block_type", [SkillBlock, GrokAgentBlock])
@pytest.mark.parametrize(
    "bom,ending", [(b"", "\r\n"), (b"\xef\xbb\xbf", "\n"), (b"\xef\xbb\xbf", "\r\n")]
)
def test_body_write_preserves_original_bom_and_line_endings(tmp_path, block_type, bom, ending):
    path = tmp_path / "context.md"
    prefix = "---\nname: reviewer\n---\n"
    original = bom + (prefix + BODY).replace("\n", ending).encode()
    path.write_bytes(original)
    block = block_type(path=path)
    body = block.find(BodyContent)[0]
    assert body.read_body(strip_code_blocks=False) == BODY

    body.write_body(NEW_BODY)

    expected = bom + (prefix + NEW_BODY).replace("\n", ending).encode()
    assert path.read_bytes() == expected
    assert read_text(path) == prefix + NEW_BODY
    assert block.body_text == NEW_BODY
    assert block_type(path=path).body_text == NEW_BODY
    block.find(BodyContent)[0].write_body(NEW_BODY)
    assert path.read_bytes() == expected


@pytest.mark.parametrize("new_body", ["New prose.\r\n", "\ufeffNew prose.\n"])
def test_body_write_refuses_text_that_read_normalization_would_change(tmp_path, new_body):
    path = tmp_path / "SKILL.md"
    original = "Review local metadata.\n"
    path.write_text(original)
    block = SkillBlock(path=path)
    body = block.find(BodyContent)[0]

    with pytest.raises(ValueError, match="frontmatter boundary"):
        body.write_body(new_body)

    assert path.read_text() == original
    assert block.body_text == original
    assert block.find(BodyContent)[0] is body
