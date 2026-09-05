"""Native-derived registry decoding controls; no host commands run in tests."""

from __future__ import annotations

import pytest

from skillsaw.formats.antigravity_registry import read_registry


def read(tmp_path, body):
    path = tmp_path / "agents.json"
    path.write_text(body)
    data, error = read_registry(path)
    assert error is None
    return data


@pytest.mark.parametrize("field", ["entries", "Entries", "ENTRIES", "entrieſ"])
def test_field_aliases_and_nullable_path(tmp_path, field):
    data = read(tmp_path, '{"' + field + '":[{"Path":"tools/agents","PATH":null}]}')
    assert data["entries"][0]["path"] == "tools/agents"
    assert data.decode_errors == []


@pytest.mark.parametrize(
    "body,paths",
    [
        ('{"entries":[{"path":"first"}],"Entries":[{"Path":"second"}]}', ["second"]),
        ('{"entries":[{"path":"first"}],"Entries":[{}]}', ["first"]),
        ('{"entries":[{"path":"first"}],"Entries":[null]}', ["first"]),
        ('{"entries":[{"path":"first"}],"Entries":[{"path":null}]}', ["first"]),
        ('{"entries":[{"path":"first"},{"path":"second"}],"Entries":[{}]}', ["first"]),
        (
            '{"entries":[{"path":"first"},{"path":"second"}],"Entries":[{}],"entries":[{},{}]}',
            ["first", "second"],
        ),
        ('{"entries":[{"path":"first"}],"Entries":[],"entries":[{}]}', [None]),
        ('{"entries":[{"path":"first"}],"Entries":null,"entries":[{}]}', [None]),
    ],
)
def test_ordered_entries_match_loaded_paths(tmp_path, body, paths):
    data = read(tmp_path, body)
    assert [entry.get("path") for entry in data["entries"]] == paths
    assert data.decode_errors == []


@pytest.mark.parametrize(
    "body,where",
    [
        ('{"Entries":42,"entries":[]}', "Entries"),
        ('{"Inherits":42,"inherits":[]}', "Inherits"),
        ('{"Entries":[{"Path":42,"path":"tools/agents"}]}', "Entries[0]"),
        ('{"entries":[{"Path":42}],"Entries":[]}', "entries[0]"),
        ('{"inherits":[42]}', "inherits[0]"),
        ('{"entries":[{"path":"tools/agents","Exclude":42,"exclude":[]}]}', "entries[0].Exclude"),
        ('{"entries":[{"path":"tools/agents","INCLUDE_ONLY":[42]}]}', "entries[0].INCLUDE_ONLY[0]"),
    ],
)
def test_replaced_and_cased_type_errors_are_retained(tmp_path, body, where):
    data = read(tmp_path, body)
    assert len(data.decode_errors) == 1
    assert data.decode_errors[0][0] == where


@pytest.mark.parametrize(
    "body",
    [
        "null",
        "{}",
        '{"Entries":null}',
        '{"entries":[null,{}, {"path":null}]}',
        '{"entries":[{"path":"tools/agents","Include_Only":[null],"EXCLUDE":null}]}',
        '{"entries":[{"path":"tools/agents","IncludeOnly":42}],"metadata":1e400}',
    ],
)
def test_accepted_empty_and_ignored_values(tmp_path, body):
    assert read(tmp_path, body).decode_errors == []


@pytest.mark.parametrize(
    "body", ["{'entries':[]}", "{entries:[]}", '{"metadata":NaN}', '{"metadata":Infinity}']
)
def test_strict_json5_and_constant_rejection(tmp_path, body):
    path = tmp_path / "agents.json"
    path.write_text(body)
    data, error = read_registry(path)
    assert data is None
    assert error
