"""Native-derived agy 1.5.11 JSONC plugin.json reader checks."""

from __future__ import annotations

import pytest

from skillsaw.formats.antigravity_plugin import read_plugin_manifest


def read(tmp_path, body):
    path = tmp_path / "plugin.json"
    path.write_text(body, encoding="utf-8")
    return read_plugin_manifest(path)


@pytest.mark.parametrize(
    "body",
    [
        '{"name":"berth-tools","license":"MIT","license":"Apache-2.0"}',
        '{"name":"berth-tools","author":{"name":"First","name":"Second"}}',
        '{"name":"berth-tools","metadata":[{"disabled":true,"disabled":false}]}',
        '{"name":"berth-tools","Name":42,"Description":42,"Disabled":42,"Logo":42}',
        '{"name":"berth-tools","Version":42,"displayname":42,"DisplayName":42}',
        '{"name":"berth-tools","metadata":1e400}',
        '\ufeff{"name":"berth-tools"}',
        '// line comment\n{"name":"berth-tools",}',
        '/* block comment */ {"name":"berth-tools"}',
        '{"name":42,"name":"berth-tools"}',
        '{"name":"berth-tools","displayName":"A","display_name":"B"}',
        r'{"name":"berth-tools","metadata":"\ud800"}',
    ],
)
def test_jsonc_bom_duplicates_and_exact_case_are_accepted(tmp_path, body):
    data, error = read(tmp_path, body)
    assert error is None
    assert data["name"] == "berth-tools"


def test_null_root_reads_as_empty_manifest(tmp_path):
    data, error = read(tmp_path, "null")
    assert error is None
    assert data == {}


def test_duplicate_key_keeps_last_value(tmp_path):
    data, error = read(
        tmp_path, '{"name":"first","name":"second","disabled":"no","disabled":false}'
    )
    assert error is None
    assert data == {"name": "second", "disabled": False}


def test_both_display_name_spellings_are_kept_independently(tmp_path):
    data, error = read(tmp_path, '{"name":"berth-tools","displayName":42,"display_name":"B"}')
    assert error is None
    assert data == {"name": "berth-tools", "displayName": 42, "display_name": "B"}


@pytest.mark.parametrize("value,expected", [(r"\ud83d\ude00", "😀"), ("航路", "航路")])
def test_valid_unicode_is_preserved(tmp_path, value, expected):
    data, error = read(tmp_path, '{"name":"berth-tools","description":"' + value + '"}')
    assert error is None
    assert data["description"] == expected


@pytest.mark.parametrize(
    "body",
    [
        '{"metadata":NaN}',
        '{"metadata":Infinity}',
        '{"metadata":-Infinity}',
        '{"name":"berth-tools"',
        "",
    ],
)
def test_malformed_json_and_non_json_constants_remain_rejected(tmp_path, body):
    data, error = read(tmp_path, body)
    assert data is None
    assert error
