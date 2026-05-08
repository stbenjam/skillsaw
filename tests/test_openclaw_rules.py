"""
Tests for openclaw metadata validation rule
"""

from skillsaw.context import RepositoryContext
from skillsaw.config import LinterConfig
from skillsaw.rule import Severity
from skillsaw.rules.builtin.openclaw import OpenclawMetadataRule

# --- config ---


def test_openclaw_default_enabled_auto():
    config = LinterConfig.default()
    assert config.get_rule_config("openclaw-metadata").get("enabled") == "auto"


def test_openclaw_default_severity_is_warning():
    rule = OpenclawMetadataRule()
    assert rule.default_severity() == Severity.WARNING


# --- skip when not present ---


def test_no_metadata_skips(temp_dir):
    skill = temp_dir / "no-meta"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: no-meta\ndescription: No metadata\n---\n")

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0


def test_metadata_without_openclaw_skips(temp_dir):
    skill = temp_dir / "other-meta"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: other-meta\ndescription: Other metadata\nmetadata:\n  version: '1.0'\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0


def test_metadata_not_a_dict_skips(temp_dir):
    skill = temp_dir / "bad-meta"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-meta\ndescription: Bad metadata\nmetadata: not-a-map\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0


def test_no_frontmatter_skips(temp_dir):
    skill = temp_dir / "no-front"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# Just markdown\n")

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0


# --- openclaw must be a mapping ---


def test_openclaw_not_a_dict_fails(temp_dir):
    skill = temp_dir / "bad-oc"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-oc\ndescription: Bad openclaw\nmetadata:\n  openclaw: not-a-map\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 1
    assert "mapping" in violations[0].message


# --- valid openclaw passes ---


def test_valid_openclaw_passes(temp_dir):
    skill = temp_dir / "good-oc"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: good-oc\ndescription: Good openclaw\nmetadata:\n"
        "  openclaw:\n"
        "    category: productivity\n"
        "    requires:\n"
        "      bins:\n"
        "        - gws\n"
        "---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0


def test_valid_openclaw_full_spec_passes(temp_dir):
    skill = temp_dir / "full-oc"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: full-oc\ndescription: Full openclaw\nmetadata:\n"
        "  openclaw:\n"
        "    always: true\n"
        "    emoji: '♊️'\n"
        "    homepage: https://example.com\n"
        "    primaryEnv: GEMINI_API_KEY\n"
        "    os:\n"
        "      - darwin\n"
        "      - linux\n"
        "    requires:\n"
        "      bins:\n"
        "        - gemini\n"
        "      anyBins:\n"
        "        - npm\n"
        "        - npx\n"
        "      env:\n"
        "        - API_KEY\n"
        "      config:\n"
        "        - some.path\n"
        "    install:\n"
        "      - id: brew\n"
        "        kind: brew\n"
        "        formula: gemini-cli\n"
        "        bins:\n"
        "          - gemini\n"
        "        label: Install Gemini CLI\n"
        "        os:\n"
        "          - darwin\n"
        "---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0


def test_empty_openclaw_passes(temp_dir):
    skill = temp_dir / "empty-oc"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: empty-oc\ndescription: Empty openclaw\nmetadata:\n  openclaw: {}\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0


# --- top-level field validation ---


def test_always_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-always"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-always\ndescription: Bad always\nmetadata:\n"
        "  openclaw:\n    always: yes-please\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("always" in v.message and "boolean" in v.message for v in violations)


def test_emoji_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-emoji"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-emoji\ndescription: Bad emoji\nmetadata:\n"
        "  openclaw:\n    emoji: 42\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("emoji" in v.message and "string" in v.message for v in violations)


def test_homepage_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-hp"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-hp\ndescription: Bad homepage\nmetadata:\n"
        "  openclaw:\n    homepage: 42\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("homepage" in v.message and "string" in v.message for v in violations)


def test_primary_env_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-env"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-env\ndescription: Bad primaryEnv\nmetadata:\n"
        "  openclaw:\n    primaryEnv: 42\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("primaryEnv" in v.message and "string" in v.message for v in violations)


def test_os_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-os"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-os\ndescription: Bad os\nmetadata:\n" "  openclaw:\n    os: darwin\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("os" in v.message and "list" in v.message for v in violations)


def test_os_non_string_items_fails(temp_dir):
    skill = temp_dir / "bad-os-items"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-os-items\ndescription: Bad os items\nmetadata:\n"
        "  openclaw:\n    os:\n      - 42\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("os" in v.message and "strings" in v.message for v in violations)


def test_os_invalid_value_fails(temp_dir):
    skill = temp_dir / "bad-os-val"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-os-val\ndescription: Bad os value\nmetadata:\n"
        "  openclaw:\n    os:\n      - darwin\n      - windows\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("invalid values" in v.message and "windows" in v.message for v in violations)


# --- requires validation ---


def test_requires_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-req"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-req\ndescription: Bad requires\nmetadata:\n"
        "  openclaw:\n    requires: not-a-map\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("requires" in v.message and "mapping" in v.message for v in violations)


def test_requires_bins_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-bins"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-bins\ndescription: Bad bins\nmetadata:\n"
        "  openclaw:\n    requires:\n      bins: gws\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("bins" in v.message and "list" in v.message for v in violations)


def test_requires_bins_non_string_items_fails(temp_dir):
    skill = temp_dir / "bad-bin-items"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-bin-items\ndescription: Bad bin items\nmetadata:\n"
        "  openclaw:\n    requires:\n      bins:\n        - 42\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("bins" in v.message and "strings" in v.message for v in violations)


def test_requires_any_bins_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-any-bins"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-any-bins\ndescription: Bad anyBins\nmetadata:\n"
        "  openclaw:\n    requires:\n      anyBins: npm\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("anyBins" in v.message and "list" in v.message for v in violations)


def test_requires_env_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-env-req"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-env-req\ndescription: Bad env\nmetadata:\n"
        "  openclaw:\n    requires:\n      env: API_KEY\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("env" in v.message and "list" in v.message for v in violations)


def test_requires_config_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-config-req"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-config-req\ndescription: Bad config\nmetadata:\n"
        "  openclaw:\n    requires:\n      config: some.path\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("config" in v.message and "list" in v.message for v in violations)


# --- install validation ---


def test_install_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-install"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-install\ndescription: Bad install\nmetadata:\n"
        "  openclaw:\n    install: not-a-list\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("install" in v.message and "list" in v.message for v in violations)


def test_install_entry_not_a_dict_fails(temp_dir):
    skill = temp_dir / "bad-entry"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-entry\ndescription: Bad entry\nmetadata:\n"
        "  openclaw:\n    install:\n      - not-a-map\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("install[0]" in v.message and "mapping" in v.message for v in violations)


def test_install_invalid_kind_fails(temp_dir):
    skill = temp_dir / "bad-kind"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-kind\ndescription: Bad kind\nmetadata:\n"
        "  openclaw:\n    install:\n      - id: test\n        kind: pip\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("kind" in v.message and "pip" in v.message for v in violations)


def test_install_download_without_url_fails(temp_dir):
    skill = temp_dir / "no-url"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: no-url\ndescription: No url\nmetadata:\n"
        "  openclaw:\n    install:\n      - id: dl\n        kind: download\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("download" in v.message and "url" in v.message for v in violations)


def test_install_download_with_url_passes(temp_dir):
    skill = temp_dir / "has-url"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: has-url\ndescription: Has url\nmetadata:\n"
        "  openclaw:\n    install:\n"
        "      - id: dl\n        kind: download\n        url: https://example.com/bin\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0


def test_install_invalid_archive_fails(temp_dir):
    skill = temp_dir / "bad-archive"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-archive\ndescription: Bad archive\nmetadata:\n"
        "  openclaw:\n    install:\n"
        "      - id: dl\n        kind: download\n        url: https://x.com/a\n"
        "        archive: rar\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("archive" in v.message and "rar" in v.message for v in violations)


def test_install_valid_archive_passes(temp_dir):
    skill = temp_dir / "good-archive"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: good-archive\ndescription: Good archive\nmetadata:\n"
        "  openclaw:\n    install:\n"
        "      - id: dl\n        kind: download\n        url: https://x.com/a\n"
        "        archive: tar.gz\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0


def test_install_extract_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-extract"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-extract\ndescription: Bad extract\nmetadata:\n"
        "  openclaw:\n    install:\n"
        "      - id: dl\n        kind: download\n        url: https://x.com/a\n"
        "        extract: maybe\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("extract" in v.message and "boolean" in v.message for v in violations)


def test_install_strip_components_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-strip"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-strip\ndescription: Bad strip\nmetadata:\n"
        "  openclaw:\n    install:\n"
        "      - id: dl\n        kind: download\n        url: https://x.com/a\n"
        "        stripComponents: one\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("stripComponents" in v.message and "number" in v.message for v in violations)


def test_install_string_fields_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-strings"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-strings\ndescription: Bad strings\nmetadata:\n"
        "  openclaw:\n    install:\n"
        "      - id: 42\n        kind: brew\n        label: 42\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("id" in v.message and "string" in v.message for v in violations)
    assert any("label" in v.message and "string" in v.message for v in violations)


def test_install_bins_wrong_type_fails(temp_dir):
    skill = temp_dir / "bad-ibins"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-ibins\ndescription: Bad install bins\nmetadata:\n"
        "  openclaw:\n    install:\n"
        "      - id: brew\n        kind: brew\n        bins: gws\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("bins" in v.message and "list" in v.message for v in violations)


def test_install_os_invalid_value_fails(temp_dir):
    skill = temp_dir / "bad-ios"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: bad-ios\ndescription: Bad install os\nmetadata:\n"
        "  openclaw:\n    install:\n"
        "      - id: brew\n        kind: brew\n        os:\n          - macos\n---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert any("invalid values" in v.message and "macos" in v.message for v in violations)


# --- real-world gws-style metadata passes ---


def test_gws_style_metadata_passes(temp_dir):
    """Real-world gws-style metadata from cblecker/claude-plugins"""
    skill = temp_dir / "gws-gmail-send"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: gws-gmail-send\n"
        "version: 1.0.0\n"
        "description: Send emails via Gmail.\n"
        "metadata:\n"
        "  openclaw:\n"
        "    category: productivity\n"
        "    requires:\n"
        "      bins:\n"
        "        - gws\n"
        "    cliHelp: gws gmail +send --help\n"
        "---\n"
    )

    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 0
