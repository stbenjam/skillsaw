"""ZCode marketplace catalog sources and entries."""

from __future__ import annotations


from ._helpers import lint, messages, rule_ids, write_json, zcode_catalog, zcode_plugin


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


def test_source_locators_and_url_subtypes_follow_the_resolver(tmp_path):
    zcode_catalog(
        tmp_path,
        [
            {"name": "blank-url", "source": {"source": "git", "url": "   "}},
            {
                "name": "zip-no-digest",
                "source": {"source": "url", "url": "https://e.com/p.zip", "type": "zip"},
            },
            {
                "name": "odd-type",
                "source": {"source": "url", "url": "https://e.com/p", "type": "tarball"},
            },
            {
                "name": "git-url",
                "source": {"source": "url", "url": "https://e.com/p.git", "type": 7},
            },
        ],
    )
    found = messages(lint(tmp_path), "zcode-marketplace-json-valid")
    assert any("'blank-url'" in m and "'url'" in m for m in found)
    assert any("'zip-no-digest'" in m and "'sha256'" in m for m in found)
    assert any("'odd-type'" in m and "must be git or zip" in m for m in found)
    assert not any("'git-url'" in m for m in found)


def test_forced_marketplace_type_attaches_listed_plugins(tmp_path):
    """No marker declares the catalog, so the forced type brings its plugins."""
    from skillsaw.context import RepositoryContext, RepositoryType
    from skillsaw.lint_target import ZCodePluginConfigNode

    plugin = tmp_path / "plugins" / "tide-charts"
    (plugin / "commands").mkdir(parents=True)
    write_json(
        tmp_path / "marketplace.json",
        {"name": "harbor", "plugins": [{"name": "tide-charts", "source": "./plugins/tide-charts"}]},
    )
    context = RepositoryContext(tmp_path, repo_types={RepositoryType.ZCODE_MARKETPLACE})
    dirs = {n.plugin_dir for n in context.lint_tree.find(ZCodePluginConfigNode)}
    assert plugin in dirs


def test_non_regular_catalog_is_not_read(tmp_path):
    import os

    zcode_plugin(tmp_path / "plugins" / "anchor", name="anchor")
    os.mkfifo(tmp_path / "marketplace.json")
    found = messages(lint(tmp_path), "zcode-marketplace-json-valid")
    assert any("not a regular file" in m for m in found)


def test_catalog_without_plugins_is_a_warning(tmp_path):
    zcode_plugin(tmp_path / "plugins" / "anchor", name="anchor")
    write_json(tmp_path / "marketplace.json", {"name": "harbor"})
    found = [
        v for v in lint(tmp_path)["violations"] if v["rule_id"] == "zcode-marketplace-json-valid"
    ]
    assert [v["severity"] for v in found] == ["warning"]


def test_absolute_string_source_is_external(tmp_path):
    zcode_catalog(tmp_path, [{"name": "elsewhere", "source": "/opt/zcode/plugins/elsewhere"}])
    assert not any(
        "'elsewhere'" in m for m in messages(lint(tmp_path), "zcode-marketplace-json-valid")
    )


def test_strict_false_entries_are_excused_under_a_forced_marketplace(tmp_path):
    loose = tmp_path / "plugins" / "loose"
    (loose / "commands").mkdir(parents=True)
    write_json(
        tmp_path / "marketplace.json",
        {
            "name": "harbor",
            "plugins": [{"name": "loose", "source": "./plugins/loose", "strict": False}],
        },
    )
    report = lint(tmp_path, "--type", "zcode-marketplace", "--type", "zcode-plugin")
    assert not messages(report, "zcode-plugin-json-valid")
    assert not messages(report, "zcode-marketplace-json-valid")
