"""Focused tests for the OpenCode configuration rule."""

import tracemalloc

import pytest

from skillsaw.rules.builtin.opencode.config_valid import (
    _json_values_equal,
    _lower_model_selection,
)


@pytest.mark.parametrize(
    ("value", "expected_items"),
    [
        ("anthropic/claude-sonnet", [("model", "anthropic/claude-sonnet")]),
        (
            "anthropic/claude-sonnet#thinking",
            [("model", "anthropic/claude-sonnet"), ("variant", "thinking")],
        ),
        (
            "anthropic/family/claude-sonnet",
            [("model", "anthropic/family/claude-sonnet")],
        ),
        (" anthropic/claude-sonnet ", [("model", " anthropic/claude-sonnet ")]),
        (
            {"providerID": "anthropic", "model": "claude-sonnet"},
            [("model", "anthropic/claude-sonnet")],
        ),
        (
            {"providerID": "anthropic", "model": "family/claude-sonnet"},
            [("model", "anthropic/family/claude-sonnet")],
        ),
        (
            {
                "providerID": "anthropic",
                "model": "claude-sonnet",
                "variant": "thinking",
                "future-field": "ignored",
            },
            [("model", "anthropic/claude-sonnet"), ("variant", "thinking")],
        ),
    ],
)
def test_lower_model_selection_preserves_accepted_forms_and_field_order(value, expected_items):
    lowered = _lower_model_selection(value)

    assert lowered is not None
    assert list(lowered.items()) == expected_items


@pytest.mark.parametrize(
    "value",
    [
        None,
        [("providerID", "anthropic"), ("model", "claude-sonnet")],
        "claude-sonnet",
        "/claude-sonnet",
        "anthropic/",
        "anthropic#host/claude-sonnet",
        "anthropic/claude-sonnet#",
        "anthropic/claude-sonnet#thinking#fast",
        {},
        {"providerID": 7, "model": "claude-sonnet"},
        {"providerID": "anthropic/team", "model": "claude-sonnet"},
        {"providerID": "anthropic#host", "model": "claude-sonnet"},
        {"providerID": "anthropic", "model": 7},
        {"providerID": "anthropic", "model": "claude-sonnet#thinking"},
        {"providerID": "anthropic", "model": "claude-sonnet", "variant": None},
        {"providerID": "anthropic", "model": "claude-sonnet", "variant": ""},
        {
            "providerID": "anthropic",
            "model": "claude-sonnet",
            "variant": "thinking#fast",
        },
    ],
)
def test_lower_model_selection_rejects_malformed_forms(value):
    assert _lower_model_selection(value) is None


def test_json_value_comparison_matches_mapping_keys_not_insertion_order():
    left = {"first": {"nested": 1}, "second": 2}
    right = {"second": 2, "first": {"nested": 1}}

    assert _json_values_equal(left, right)


def test_json_value_comparison_memory_tracks_depth_not_container_width():
    """A wide, hostile config must not allocate one work item per child."""
    values = range(100_000)
    pairs = [
        (list(values), list(values)),
        ({str(value): value for value in values}, {str(value): value for value in values}),
    ]

    for left, right in pairs:
        tracemalloc.start()
        try:
            assert _json_values_equal(left, right)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert peak < 2 * 1024 * 1024
