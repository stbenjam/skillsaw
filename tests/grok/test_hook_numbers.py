"""Grok reads a hook ``timeout`` as a JSON number of seconds.

Measured against Grok Build 1.0.77: every spelling of zero, a fraction and a
value past ``u64`` load; a negative, a bool and a numeric string drop the
handler alone.
"""

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokHooksValidRule
from tests.test_integration import copy_fixture


@pytest.mark.parametrize(
    "token,accepted",
    [
        ("0", True),
        ("-0", True),
        ("0.0", True),
        ("-0.0", True),
        ("0e0", True),
        ("1.5", True),
        ("1e-300", True),
        ("null", True),
        ("18446744073709551616", True),
        ("-1", False),
        ("-0.5", False),
        ("true", False),
        ('"30"', False),
    ],
)
def test_timeout_tokens_follow_the_native_number_decoder(tmp_path, token, accepted):
    repo = copy_fixture("grok/hook-numbers/zero", tmp_path)
    path = repo / ".grok/hooks/numbers.json"
    path.write_text(path.read_text().replace('"timeout": 0', '"timeout": ' + token))
    found = GrokHooksValidRule().check(RepositoryContext(repo))
    assert len(found) == (0 if accepted else 1)
    if not accepted:
        assert found[0].file_path == path
        assert "'timeout' must be a non-negative number" in found[0].message
        assert found[0].severity == Severity.WARNING
