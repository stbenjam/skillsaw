"""Focused tests for the OpenCode configuration rule."""

import tracemalloc

from skillsaw.rules.builtin.opencode.config_valid import _json_values_equal


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
