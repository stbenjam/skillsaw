"""Contract tests for the shared credential detector.

The values here are deliberately meaningless strings — the point is the
name/value classification, never a realistic credential.
"""

import pytest

from skillsaw.rules.builtin.secret_detection import (
    DEFAULT_PLACEHOLDER_MARKERS,
    mapped_secret_description,
)

# Opaque, high-variety, and matching no structured token format.
OPAQUE = "Qz7Rm4Wp9Lv2Bs6H"
# Shaped like a GitHub token so the structured branch fires; not a real one.
STRUCTURED = "ghp_" + "aB3cD4eF5gH6iJ7kL8mN9pQ0rS1uV2wX3yZ4"

HEADER_CREDENTIAL = "credential-bearing HTTP header"
ENV_CREDENTIAL = "credential-bearing environment variable"


class TestMappedSecretDescription:
    @pytest.mark.parametrize(
        ("name", "value", "header", "expected"),
        [
            # Credential-bearing names, by suffix and by exact match.
            ("X-Vendor-Client-Secret", OPAQUE, True, HEADER_CREDENTIAL),
            ("SERVICE_PASSWORD", OPAQUE, False, ENV_CREDENTIAL),
            ("X-Api-Key", OPAQUE, True, HEADER_CREDENTIAL),
            # Separator runs and case fold to the same normalized name.
            ("x-API--key", OPAQUE, True, HEADER_CREDENTIAL),
            # 'authorization' is a header name only; as an env name it is not
            # in the deliberately narrow env list.
            ("authorization", OPAQUE, True, HEADER_CREDENTIAL),
            ("authorization", OPAQUE, False, None),
            # Neutral names carry no credential signal on their own.
            ("X-Trace-Id", OPAQUE, True, None),
            ("SERVICE_ENDPOINT", OPAQUE, False, None),
            # Placeholders under a credential name are permitted.
            ("API_KEY", "${API_KEY}", False, None),
            ("X-Api-Key", "<your-api-key>", True, None),
            # Structured tokens are reported whatever the name says.
            ("X-Trace-Id", STRUCTURED, True, "GitHub personal access token"),
            ("SERVICE_ENDPOINT", STRUCTURED, False, "GitHub personal access token"),
        ],
    )
    def test_classification(self, name, value, header, expected):
        assert mapped_secret_description(name, value, header=header) == expected

    def test_structured_tokens_outrank_placeholder_suppression(self):
        # A placeholder marker in the same value must not hide a real token
        # format — the structured check runs first, by design.
        assert (
            mapped_secret_description(
                "X-Api-Key",
                f"example-{STRUCTURED}",
                header=True,
            )
            == "GitHub personal access token"
        )

    @pytest.mark.parametrize("marker", ["password", "token"])
    def test_password_and_token_stay_substring_placeholders(self, marker):
        # Issue #322 corpus: these two words are placeholder markers anywhere
        # in the value, not only as a whole word.
        assert marker in DEFAULT_PLACEHOLDER_MARKERS
        value = f"rotate-this-{marker}-later"
        assert mapped_secret_description("API_KEY", value, header=False) is None

    def test_additional_markers_suppress_a_project_convention(self):
        value = "corp-vault-9f2b41d7c6"

        assert mapped_secret_description("X-Api-Key", value, header=True) == HEADER_CREDENTIAL
        assert (
            mapped_secret_description(
                "X-Api-Key",
                value,
                header=True,
                markers=DEFAULT_PLACEHOLDER_MARKERS + ("corp-vault-",),
            )
            is None
        )

    def test_additional_markers_never_weaken_structured_detection(self):
        assert (
            mapped_secret_description(
                "X-Api-Key",
                f"corp-vault-{STRUCTURED}",
                header=True,
                markers=DEFAULT_PLACEHOLDER_MARKERS + ("corp-vault-",),
            )
            == "GitHub personal access token"
        )

    def test_values_are_never_echoed_in_the_description(self):
        description = mapped_secret_description("SERVICE_PASSWORD", OPAQUE, header=False)

        assert description is not None
        assert OPAQUE not in description
