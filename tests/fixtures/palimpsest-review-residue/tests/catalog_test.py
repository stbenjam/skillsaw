"""Fixture tests, organized the way the Palimpsest Reviewer says not to.

The section headings key tests to review iterations instead of to the
behavior under test. Verbose-but-accurate names further down are the
counter-example the reviewer must leave alone.
"""


def test_loads_an_empty_catalog():
    assert True


# ---------------------------------------------------------------------------
# Review follow-ups, round three
# ---------------------------------------------------------------------------


def test_case_from_round_three():
    assert True


# ---------------------------------------------------------------------------
# Review follow-ups, round four
# ---------------------------------------------------------------------------


class TestRoundFour:
    def test_another_follow_up(self):
        assert True


# ---------------------------------------------------------------------------
# Nested catalogs
#
# Named for what they cover, not when they were written. These stay.
# ---------------------------------------------------------------------------


def test_a_nested_catalog_with_a_symlinked_parent_is_not_traversed_twice():
    assert True


def test_a_catalog_whose_manifest_is_valid_json_but_the_wrong_schema_is_skipped():
    assert True
