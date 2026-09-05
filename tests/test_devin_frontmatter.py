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


@pytest.mark.parametrize("key", ["name", "description", "argument-hint", "model", "agent"])
@pytest.mark.parametrize("value", ["42", "1e3", "0123", "true", "yes", "2026-09-04"])
def test_native_skill_string_fields_preserve_lexical_scalars(tmp_path, key, value):
    path = tmp_path / "SKILL.md"
    source = f"---\n{key}: {value}\n---\nReview local metadata.\n"
    path.write_text(source)
    block = DevinSkillBlock(path=path)

    assert block.field_value(key) == value
    assert block.field(key).field_line == 2
    assert block.body_text == "Review local metadata.\n"
    assert path.read_text() == source


@pytest.mark.parametrize(
    "value,expected",
    [("true", True), ("False", False), ("yes", "yes"), ("off", "off"), ('"true"', "true")],
)
def test_native_subagent_retains_actual_boolean_contract(tmp_path, value, expected):
    path = tmp_path / "SKILL.md"
    path.write_text(f"---\nsubagent: {value}\n---\nReview local metadata.\n")
    value = DevinSkillBlock(path=path).field_value("subagent")

    assert value == expected
    assert type(value) is type(expected)


@pytest.mark.parametrize(
    "block_type,key",
    [(DevinSkillBlock, "allowed-tools"), (DevinSkillBlock, "triggers"), (DevinRuleBlock, "globs")],
)
def test_native_string_lists_preserve_scalar_text(tmp_path, block_type, key):
    path = tmp_path / "context.md"
    path.write_text(
        f"---\n{key}: [42, false, yes, null, ~, 2026-09-04]\n---\nReview local metadata.\n"
    )

    assert block_type(path=path).field_value(key) == [
        "42",
        "false",
        "yes",
        "null",
        "~",
        "2026-09-04",
    ]


def test_native_permission_lists_preserve_scalar_text(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\npermissions:\n  allow: [42, false, null]\n  deny: [yes]\n  ask: [2026-09-04]\n---\nReview local metadata.\n"
    )

    assert DevinSkillBlock(path=path).field_value("permissions") == {
        "allow": ["42", "false", "null"],
        "deny": ["yes"],
        "ask": ["2026-09-04"],
    }


def test_native_alias_conversion_does_not_retype_unknown_extension(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\nfuture: &tools [yes, 42]\nallowed-tools: *tools\n---\nReview local metadata.\n"
    )
    block = DevinSkillBlock(path=path)

    assert block.field_value("future") == [True, 42]
    assert block.field_value("allowed-tools") == ["yes", "42"]
    fields = block.find(BodyContent)
    assert block.find(BodyContent)[0] is fields[0]


@pytest.mark.parametrize("key", ["description", "trigger"])
def test_native_rule_string_fields_preserve_scalars(tmp_path, key):
    path = tmp_path / "rule.md"
    path.write_text(f"---\n{key}: yes\n---\nReview local metadata.\n")

    assert DevinRuleBlock(path=path).field_value(key) == "yes"


def test_portable_skill_yaml_scalar_contract_is_unchanged(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\ndescription: yes\nsubagent: on\nallowed-tools: [42]\n---\nReview local metadata.\n"
    )
    block = SkillBlock(path=path)

    assert block.field_value("description") is True
    assert block.field_value("subagent") is True
    assert block.field_value("allowed-tools") == [42]


@pytest.mark.parametrize("block_type", [DevinRuleBlock, DevinSkillBlock])
def test_native_merge_key_does_not_invent_known_fields(tmp_path, block_type):
    path = tmp_path / "context.md"
    path.write_text(
        "---\ndefaults: &defaults\n  description: []\n<<: *defaults\n---\nReview local metadata.\n"
    )
    block = block_type(path=path)

    assert block.frontmatter_error is None
    assert block.field("description") is None
    assert block.field_value("defaults") == {"description": []}
    assert SkillBlock(path=path).field_value("description") == []


def test_native_permissions_ignore_merge_key_but_keep_explicit_fields(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\ndefaults: &defaults\n  allow: invalid-scalar\npermissions:\n  <<: *defaults\n  deny: [Read]\n---\nReview local metadata.\n"
    )
    permissions = DevinSkillBlock(path=path).field_value("permissions")

    assert "allow" not in permissions
    assert permissions["deny"] == ["Read"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("name", "review"),
        ("description", "Review metadata"),
        ("argument-hint", "path"),
        ("model", "sonnet"),
        ("agent", "reviewer"),
        ("subagent", "false"),
        ("allowed-tools", "[Read]"),
        ("permissions", "{allow: [Read]}"),
        ("triggers", "[user]"),
    ],
)
def test_native_skill_rejects_duplicate_known_fields_at_repeated_key(tmp_path, key, value):
    path = tmp_path / "SKILL.md"
    path.write_text(f"---\n{key}: {value}\n{key}: {value}\n---\nReview local metadata.\n")
    block = DevinSkillBlock(path=path)

    assert block.frontmatter_error == f"Duplicate frontmatter field '{key}'"
    assert block.frontmatter_error_line == 3


@pytest.mark.parametrize(
    "key,value", [("trigger", "manual"), ("description", "Review metadata"), ("globs", "[src/**]")]
)
def test_native_rule_rejects_duplicate_known_fields(tmp_path, key, value):
    path = tmp_path / "rule.md"
    path.write_text(f"---\n{key}: {value}\n{key}: {value}\n---\nReview local metadata.\n")
    block = DevinRuleBlock(path=path)

    assert block.frontmatter_error == f"Duplicate frontmatter field '{key}'"
    assert block.frontmatter_error_line == 3


@pytest.mark.parametrize("first,second", [("null", "review"), ("review", "null"), ("null", "null")])
def test_native_null_still_counts_as_a_declared_field(tmp_path, first, second):
    path = tmp_path / "SKILL.md"
    path.write_text(f"---\nname: {first}\nname: {second}\n---\nReview local metadata.\n")
    block = DevinSkillBlock(path=path)

    assert block.frontmatter_error == "Duplicate frontmatter field 'name'"
    assert block.frontmatter_error_line == 3


@pytest.mark.parametrize("key", ["allow", "deny", "ask"])
def test_native_duplicate_permissions_keep_nested_source_line(tmp_path, key):
    path = tmp_path / "SKILL.md"
    path.write_text(
        f"---\npermissions:\n  {key}: [Read]\n  {key}: [Read]\n---\nReview local metadata.\n"
    )
    block = DevinSkillBlock(path=path)

    assert block.frontmatter_error == f"Duplicate frontmatter field 'permissions.{key}'"
    assert block.frontmatter_error_line == 4


@pytest.mark.parametrize("block_type", [DevinRuleBlock, DevinSkillBlock])
def test_native_unknown_duplicates_remain_accepted(tmp_path, block_type):
    path = tmp_path / "context.md"
    path.write_text("---\nfuture: first\nfuture: second\n---\nReview local metadata.\n")
    block = block_type(path=path)

    assert block.frontmatter_error is None
    assert block.field_value("future") == "second"


def test_native_unknown_permission_duplicates_remain_accepted(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(
        "---\npermissions:\n  future: first\n  future: second\n  allow: [Read]\n---\nReview local metadata.\n"
    )
    block = DevinSkillBlock(path=path)

    assert block.frontmatter_error is None
    assert block.field_value("permissions")["allow"] == ["Read"]


def test_portable_duplicate_policy_is_unchanged(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: first\nname: second\n---\nReview local metadata.\n")
    block = SkillBlock(path=path)

    assert block.frontmatter_error is None
    assert block.field_value("name") == "second"
