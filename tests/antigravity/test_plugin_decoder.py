"""Native-derived ProtoJSON grammar checks, kept distinct from Go configs."""

from __future__ import annotations

import pytest

from skillsaw.formats.antigravity_plugin import read_plugin_manifest


def read(tmp_path, body):
    path = tmp_path / "plugin.json"
    path.write_text(body)
    return read_plugin_manifest(path)


@pytest.mark.parametrize(
    "body",
    [
        '{"name":"berth-tools","version":"1","version":"2"}',
        '{"name":"berth-tools","author":{"name":"First","name":"Second"}}',
        '{"name":"berth-tools","metadata":[{"disabled":true,"disabled":false}]}',
        '{"name":"berth-tools","Name":42,"Description":42,"Disabled":42,"Logo":42}',
        '{"name":"berth-tools","metadata":1e400}',
    ],
)
def test_unknown_duplicates_and_cased_fields_are_accepted(tmp_path, body):
    data, error = read(tmp_path, body)
    assert error is None
    assert data["name"] == "berth-tools"


@pytest.mark.parametrize("field", ["name", "description", "disabled", "logo"])
@pytest.mark.parametrize("values", ["null,null", 'null,"text"', '"text",null'])
def test_duplicate_known_fields_reject_both_null_orders(tmp_path, field, values):
    first, second = values.split(",")
    data, error = read(tmp_path, '{"' + field + '":' + first + ',"' + field + '":' + second + "}")
    assert data is None
    assert error == f'duplicate JSON object key: "{field}"'


def test_escaped_known_key_is_the_same_field(tmp_path):
    data, error = read(tmp_path, r'{"name":"first","na\u006de":"second"}')
    assert data is None
    assert error == 'duplicate JSON object key: "name"'


@pytest.mark.parametrize(
    "body",
    [
        r'{"name":"berth-tools","description":"\ud800"}',
        r'{"name":"berth-tools","metadata":"\udc00"}',
        r'{"name":"berth-tools","metadata":{"\ud800":"value"}}',
        r'{"name":"berth-tools","metadata":[["\ud800"]]}',
        r'{"name":"berth-tools","metadata":"\ud800","metadata":"fine"}',
    ],
)
def test_invalid_unicode_in_discarded_values_and_keys_is_fatal(tmp_path, body):
    data, error = read(tmp_path, body)
    assert data is None
    assert error == "invalid Unicode surrogate in JSON string"
    error.encode("utf-8")


@pytest.mark.parametrize("value,expected", [(r"\ud83d\ude00", "😀"), ("航路", "航路")])
def test_valid_unicode_is_preserved(tmp_path, value, expected):
    data, error = read(tmp_path, '{"name":"berth-tools","description":"' + value + '"}')
    assert error is None
    assert data["description"] == expected


@pytest.mark.parametrize(
    "body", ['{"metadata":NaN}', '{"metadata":Infinity}', "// note\n{}", '{"name":"berth-tools",}']
)
def test_jsonc_and_non_json_constants_remain_rejected(tmp_path, body):
    data, error = read(tmp_path, body)
    assert data is None
    assert error
