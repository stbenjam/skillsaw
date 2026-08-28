"""Contract tests for the shared credential detector.

The values here are deliberately meaningless strings — the point is the
name/value classification, never a realistic credential.
"""

import pytest

from skillsaw.rules.builtin.secret_detection import (
    DEFAULT_PLACEHOLDER_MARKERS,
    is_secret_placeholder,
    mapped_secret_description,
    placeholder_markers,
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


class TestOpenCodeSubstitutionSyntax:
    """`{env:VAR}` and `{file:./path}` are how OpenCode keeps a token out of a config."""

    @pytest.mark.parametrize(
        "value",
        [
            "{env:MY_API_KEY}",
            "Bearer {env:SENTRY_MCP_TOKEN}",
            "{file:./secrets/token}",
            "{file:~/.config/token}",
        ],
    )
    def test_substitution_syntax_reads_as_a_placeholder(self, value):
        assert is_secret_placeholder(value)

    def test_a_structured_token_is_reported_even_beside_the_syntax(self):
        """The widening must not become a way to smuggle a real token past the scan.

        `mapped_secret_description` runs the structured detector first, so a
        recognisable token format is reported whatever else the value holds.
        """
        described = mapped_secret_description(
            "GITHUB_TOKEN",
            "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789 {env:UNUSED}",  # notsecret
            header=False,
            markers=DEFAULT_PLACEHOLDER_MARKERS,
        )
        assert described == "GitHub personal access token"

    def test_a_generic_credential_is_still_reported_without_the_syntax(self):
        described = mapped_secret_description(
            "API_KEY",
            "9f8e7d6c5b4a39281706fedcba9876543210",  # notsecret
            header=False,
            markers=DEFAULT_PLACEHOLDER_MARKERS,
        )
        assert described is not None


class TestPlaceholderMarkers:
    """One reader, so the same config line means the same thing in every rule."""

    @pytest.mark.parametrize("extra", [["corp"], ("corp",), {"corp"}, frozenset({"corp"})])
    def test_every_sequence_shape_contributes(self, extra):
        assert "corp" in placeholder_markers(extra)

    @pytest.mark.parametrize("extra", [None, 42, "corp", {"corp": True}])
    def test_a_non_sequence_contributes_nothing(self, extra):
        assert placeholder_markers(extra) == DEFAULT_PLACEHOLDER_MARKERS

    def test_markers_are_lowercased_for_the_case_insensitive_match(self):
        assert "corpfixture" in placeholder_markers(["CorpFixture"])
