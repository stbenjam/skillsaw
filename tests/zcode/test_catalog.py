"""ZCode marketplace catalog sources and entries."""

from __future__ import annotations


from ._helpers import lint, messages, rule_ids, zcode_catalog


def test_unhashable_source_kind_is_a_finding_not_a_crash(tmp_path):
    zcode_catalog(tmp_path, [{"name": "odd", "source": {"source": []}}])
    report = lint(tmp_path)
    assert "rule-execution-error" not in rule_ids(report)
    assert any(
        "unsupported source kind" in m for m in messages(report, "zcode-marketplace-json-valid")
    )


def test_recognized_source_kinds_need_their_locator(tmp_path):
    zcode_catalog(
        tmp_path,
        [
            {"name": "no-repo", "source": {"source": "github"}},
            {"name": "no-url", "source": {"source": "git-subdir", "path": "plugins/x"}},
            {"name": "fine", "source": {"source": "github", "repo": "harbor/fine"}},
        ],
    )
    found = messages(lint(tmp_path), "zcode-marketplace-json-valid")
    assert any("'no-repo'" in m and "'repo'" in m for m in found)
    assert any("'no-url'" in m and "'url'" in m for m in found)
    assert not any("'fine'" in m for m in found)


def test_forced_marketplace_type_reports_a_missing_catalog(tmp_path):
    (tmp_path / "README.md").write_text("# Harbor\n")
    found = messages(lint(tmp_path, "--type", "zcode-marketplace"), "zcode-marketplace-json-valid")
    assert any("No marketplace.json" in m for m in found)


def test_invalid_entry_name_is_reported_for_remote_sources(tmp_path):
    zcode_catalog(
        tmp_path, [{"name": "Bad Plugin!", "source": {"source": "github", "repo": "h/b"}}]
    )
    found = messages(lint(tmp_path), "zcode-marketplace-json-valid")
    assert any("'Bad Plugin!'" in m and "never installs" in m for m in found)
