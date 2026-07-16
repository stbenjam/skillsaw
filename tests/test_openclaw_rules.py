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
    matching = [v for v in violations if "primaryEnv" in v.message and "string" in v.message]
    assert len(matching) == 1


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


# --- line number reporting ---


def test_line_numbers_on_openclaw_not_a_dict(temp_dir):
    skill = temp_dir / "ln-oc"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"  # 1
        "name: ln-oc\n"  # 2
        "description: test\n"  # 3
        "metadata:\n"  # 4
        "  openclaw: not-a-map\n"  # 5
        "---\n"
    )
    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 1
    assert violations[0].line == 5


def test_line_numbers_on_top_level_field(temp_dir):
    skill = temp_dir / "ln-top"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"  # 1
        "name: ln-top\n"  # 2
        "description: test\n"  # 3
        "metadata:\n"  # 4
        "  openclaw:\n"  # 5
        "    always: yes-please\n"  # 6
        "---\n"
    )
    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 1
    assert violations[0].line == 6


def test_line_numbers_on_requires_field(temp_dir):
    skill = temp_dir / "ln-req"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"  # 1
        "name: ln-req\n"  # 2
        "description: test\n"  # 3
        "metadata:\n"  # 4
        "  openclaw:\n"  # 5
        "    requires:\n"  # 6
        "      bins: gws\n"  # 7
        "---\n"
    )
    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 1
    assert violations[0].line == 7


def test_line_numbers_on_install_field(temp_dir):
    skill = temp_dir / "ln-inst"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"  # 1
        "name: ln-inst\n"  # 2
        "description: test\n"  # 3
        "metadata:\n"  # 4
        "  openclaw:\n"  # 5
        "    install:\n"  # 6
        "      - id: test\n"  # 7
        "        kind: pip\n"  # 8
        "---\n"
    )
    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 1
    assert violations[0].line == 8


def test_line_numbers_on_os_field(temp_dir):
    skill = temp_dir / "ln-os"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"  # 1
        "name: ln-os\n"  # 2
        "description: test\n"  # 3
        "metadata:\n"  # 4
        "  openclaw:\n"  # 5
        "    os: darwin\n"  # 6
        "---\n"
    )
    context = RepositoryContext(skill)
    violations = OpenclawMetadataRule().check(context)
    assert len(violations) == 1
    assert violations[0].line == 6


# --- Tier A: type alias, per-kind required fields, extra fields, typos ---


def _skill(temp_dir, name, openclaw_yaml):
    skill = temp_dir / name
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\nmetadata:\n  openclaw:\n{openclaw_yaml}---\n"
    )
    context = RepositoryContext(skill)
    return OpenclawMetadataRule().check(context)


def test_type_alias_invalid_kind_fails(temp_dir):
    # openclaw accepts `type` as an alias for `kind`
    v = _skill(temp_dir, "type-bad", "    install:\n      - id: x\n        type: pip\n")
    assert any("type" in m.message and "pip" in m.message for m in v)


def test_type_alias_valid_kind_passes(temp_dir):
    v = _skill(
        temp_dir,
        "type-ok",
        "    install:\n      - id: x\n        type: node\n        package: '@scope/x'\n",
    )
    assert len(v) == 0


def test_kind_case_insensitive_passes(temp_dir):
    # openclaw lowercases the kind before matching
    v = _skill(
        temp_dir,
        "kind-case",
        "    install:\n      - id: x\n        kind: Node\n        package: x\n",
    )
    assert len(v) == 0


def test_install_without_kind_or_type_fails(temp_dir):
    v = _skill(temp_dir, "kind-missing", "    install:\n      - id: x\n")
    assert any("must specify 'kind' or 'type'" in m.message for m in v)


def test_install_null_kind_fails(temp_dir):
    v = _skill(temp_dir, "kind-null", "    install:\n      - id: x\n        kind: null\n")
    assert any("install[0].kind" in m.message and "string" in m.message for m in v)


def test_install_non_string_kind_falls_back_to_type(temp_dir):
    v = _skill(
        temp_dir,
        "kind-type-fallback",
        "    install:\n"
        "      - id: x\n"
        "        kind: null\n"
        "        type: node\n"
        "        package: x\n",
    )
    assert len(v) == 0


def test_brew_without_formula_or_cask_fails(temp_dir):
    v = _skill(temp_dir, "brew-none", "    install:\n      - id: b\n        kind: brew\n")
    assert any("brew" in m.message and "formula" in m.message for m in v)


def test_brew_with_cask_passes(temp_dir):
    v = _skill(
        temp_dir,
        "brew-cask",
        "    install:\n      - id: b\n        kind: brew\n        cask: some-cask\n",
    )
    assert len(v) == 0


def test_node_without_package_fails(temp_dir):
    v = _skill(temp_dir, "node-none", "    install:\n      - id: n\n        kind: node\n")
    assert any("node" in m.message and "package" in m.message for m in v)


def test_go_without_module_fails(temp_dir):
    v = _skill(temp_dir, "go-none", "    install:\n      - id: g\n        kind: go\n")
    assert any("go" in m.message and "module" in m.message for m in v)


def test_uv_without_package_fails(temp_dir):
    v = _skill(temp_dir, "uv-none", "    install:\n      - id: u\n        kind: uv\n")
    assert any("uv" in m.message and "package" in m.message for m in v)


def test_go_with_module_passes(temp_dir):
    v = _skill(
        temp_dir,
        "go-ok",
        "    install:\n      - id: g\n        kind: go\n        module: example.com/x/cmd/y\n",
    )
    assert len(v) == 0


def test_install_package_wrong_type_fails(temp_dir):
    v = _skill(
        temp_dir,
        "pkg-type",
        "    install:\n      - id: n\n        kind: node\n        package: 42\n",
    )
    assert any("package" in m.message and "string" in m.message for m in v)


def test_apikey_wrong_type_fails(temp_dir):
    v = _skill(temp_dir, "apikey", "    apiKey: 42\n")
    assert any("apiKey" in m.message and "string" in m.message for m in v)


def test_hidden_wrong_type_fails(temp_dir):
    v = _skill(temp_dir, "hidden", "    hidden: nope\n")
    assert any("hidden" in m.message and "boolean" in m.message for m in v)


def test_skillkey_wrong_type_fails(temp_dir):
    v = _skill(temp_dir, "skillkey", "    skillKey: 42\n")
    assert any("skillKey" in m.message and "string" in m.message for m in v)


def test_typo_key_near_miss_warns(temp_dir):
    # `installs`/`require` are near-misses of known keys -> did-you-mean
    v = _skill(temp_dir, "typo", "    installs: []\n")
    assert any("did you mean" in m.message and "install" in m.message for m in v)


def test_clawhub_metadata_keys_pass(temp_dir):
    v = _skill(
        temp_dir,
        "clawhub",
        "    category: productivity\n    cliHelp: tool --help\n",
    )
    assert len(v) == 0


def test_clawhub_metadata_key_typos_warn(temp_dir):
    category = _skill(temp_dir, "category-typo", "    categry: productivity\n")
    cli_help = _skill(temp_dir, "clihelp-typo", "    clihelp: tool --help\n")
    assert any("did you mean 'category'" in m.message for m in category)
    assert any("did you mean 'cliHelp'" in m.message for m in cli_help)


def test_non_string_openclaw_key_does_not_crash(temp_dir):
    v = _skill(temp_dir, "numeric-key", "    1: value\n")
    assert len(v) == 0
