"""Regression coverage for untrusted Agent Plugin diagnostic text."""

import json

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.formatters import format_report
from skillsaw.formats.agent_plugins import MCP_SCHEMA_ID, PLUGIN_SCHEMA_ID
from skillsaw.linter import Linter

from ._helpers import MANIFEST_RULE, MCP_RULE


def _contains_surrogate(text: str) -> bool:
    return any("\ud800" <= character <= "\udfff" for character in text)


def _messages(output: str, output_format: str) -> list[str]:
    if output_format == "text":
        return [line for line in output.splitlines() if "\N{REPLACEMENT CHARACTER}" in line]
    report = json.loads(output)
    if output_format == "json":
        return [finding["message"] for finding in report["violations"]]
    return [finding["message"]["text"] for finding in report["runs"][0]["results"]]


@pytest.mark.parametrize("output_format", ["text", "json", "sarif"])
def test_escaped_lone_surrogate_keys_are_safe_in_every_output_format(
    tmp_path,
    output_format,
):
    """Escaped JSON keys must not leave an unencodable diagnostic behind."""
    (tmp_path / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": PLUGIN_SCHEMA_ID,
                "name": "diagnostic-safety",
                "\ud800manifest-field": True,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": MCP_SCHEMA_ID,
                "mcpServers": {
                    "\udfffserver": {"type": "stdio", "command": ""},
                },
            }
        ),
        encoding="utf-8",
    )
    assert "\\ud800" in (tmp_path / "plugin.json").read_text(encoding="utf-8")
    assert "\\udfff" in (tmp_path / "mcp.json").read_text(encoding="utf-8")

    context = RepositoryContext(tmp_path)
    config = LinterConfig.default()
    config.version = "99.0.0"
    linter = Linter(context, config=config, rule_ids={MANIFEST_RULE, MCP_RULE})
    findings = linter.run()

    assert len(findings) == 2
    assert all(not _contains_surrogate(finding.message) for finding in findings)
    output = format_report(output_format, findings, context, linter.rules, "0.18.0")

    # This is where plain text output used to raise UnicodeEncodeError. JSON
    # and SARIF are checked too so a future formatter change cannot re-expose
    # the escaped code point.
    output.encode("utf-8")
    assert not _contains_surrogate(output)
    assert "\\ud800" not in output.lower()
    assert "\\udfff" not in output.lower()
    rendered_messages = _messages(output, output_format)
    assert len(rendered_messages) == 2
    assert all(not _contains_surrogate(message) for message in rendered_messages)
    assert all("\N{REPLACEMENT CHARACTER}" in message for message in rendered_messages)
