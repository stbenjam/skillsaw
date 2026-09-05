"""Native Devin frontmatter boundaries stay separate from portable skills."""

import pytest

from skillsaw.blocks import BodyContent, DevinRuleBlock, DevinSkillBlock, SkillBlock


@pytest.mark.parametrize("block_type", [DevinRuleBlock, DevinSkillBlock])
@pytest.mark.parametrize(
    "frontmatter,link_line",
    [("", 5), ("\n", 6), ("   \n", 6), ("# Optional settings\n", 6), ("{}\n", 6)],
)
def test_native_empty_headers_preserve_body_and_markdown_lines(
    tmp_path, block_type, frontmatter, link_line
):
    path = tmp_path / "context.md"
    body = "# Review\n\nRead the [guide](guide.md) before changing the API.\n"
    source = "---\n" + frontmatter + "---\n" + body
    path.write_text(source)
    block = block_type(path=path)

    assert block.frontmatter_error is None
    assert block.has_frontmatter
    assert block.body_text == body
    contents = block.find(BodyContent)
    assert len(contents) == 1
    assert contents[0].markdown.links()[0].file_line == link_line
    assert path.read_text() == source


@pytest.mark.parametrize("block_type", [DevinRuleBlock, DevinSkillBlock])
@pytest.mark.parametrize(
    "frontmatter", ["null\n", "~\n", "true\n", "[]\n", "name: [unterminated\n"]
)
def test_native_nonmapping_and_malformed_headers_remain_errors(tmp_path, block_type, frontmatter):
    path = tmp_path / "context.md"
    path.write_text("---\n" + frontmatter + "---\nReview the requested metadata.\n")
    block = block_type(path=path)

    assert block.frontmatter_error is not None
    assert "Invalid frontmatter" in block.frontmatter_error
    assert not block.has_frontmatter


@pytest.mark.parametrize("block_type", [DevinRuleBlock, DevinSkillBlock])
def test_native_missing_closing_delimiter_remains_an_error(tmp_path, block_type):
    path = tmp_path / "context.md"
    path.write_text("---\n# Optional metadata\nReview the requested metadata.\n")
    block = block_type(path=path)

    assert block.frontmatter_error is not None
    assert not block.has_frontmatter


@pytest.mark.parametrize("frontmatter", ["", "# Optional metadata\n"])
def test_portable_skill_empty_header_contract_is_unchanged(tmp_path, frontmatter):
    path = tmp_path / "SKILL.md"
    path.write_text("---\n" + frontmatter + "---\nReview the requested metadata.\n")

    assert SkillBlock(path=path).frontmatter_error is not None
