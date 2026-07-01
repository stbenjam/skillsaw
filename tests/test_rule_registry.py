"""Tests for the auto-discovered builtin rule registry.

The registry (``skillsaw.rules.builtin``) walks the package for concrete
``Rule`` subclasses; ``LinterConfig.default()`` is generated from it. These
tests guard the invariants that made the old hand-maintained lists drift.
"""

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.rule import Rule, Severity
from skillsaw.rules.builtin import BUILTIN_RULES, BUILTIN_RULE_REGISTRY


def test_registry_discovers_rules():
    assert len(BUILTIN_RULES) >= 53
    ids = [cls().rule_id for cls in BUILTIN_RULES]
    assert "skill-frontmatter" in ids
    assert "plugin-json-required" in ids
    assert "content-weak-language" in ids


def test_registry_ids_unique_and_sorted():
    ids = list(BUILTIN_RULE_REGISTRY)
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert list(BUILTIN_RULE_REGISTRY.values()) == BUILTIN_RULES


def test_registry_classes_are_concrete_rules():
    for cls in BUILTIN_RULES:
        assert issubclass(cls, Rule)
        rule = cls()  # must be instantiable with no config
        assert rule.rule_id
        assert rule.description


def test_default_enabled_values_are_valid():
    for cls in BUILTIN_RULES:
        assert cls.default_enabled in (True, False, "auto"), (
            f"{cls.__name__}.default_enabled must be True, False, or 'auto', "
            f"got {cls.default_enabled!r}"
        )


def test_default_config_generated_from_registry():
    """default() must cover every builtin rule with the class-level defaults.

    This is the anti-drift guard: the old hand-maintained dict in
    ``LinterConfig.default()`` silently overrode ``Rule.default_severity()``.
    """
    defaults = LinterConfig.default().rules
    assert set(defaults) == set(BUILTIN_RULE_REGISTRY)
    for rule_id, cls in BUILTIN_RULE_REGISTRY.items():
        rule = cls()
        assert defaults[rule_id]["enabled"] == cls.default_enabled
        assert defaults[rule_id]["severity"] == rule.default_severity().value


def test_class_severity_is_effective_severity():
    """A rule constructed with its default config keeps its class severity."""
    config = LinterConfig.default()
    for rule_id, cls in BUILTIN_RULE_REGISTRY.items():
        rule = cls(config.get_rule_config(rule_id))
        assert rule.severity == cls().default_severity(), rule_id


def test_backward_compatible_class_imports():
    # Individual class imports must keep working without a re-export block
    from skillsaw.rules.builtin import SkillFrontmatterRule  # noqa: F401
    from skillsaw.rules.builtin import ContentWeakLanguageRule  # noqa: F401

    with pytest.raises(ImportError):
        from skillsaw.rules.builtin import NoSuchRule  # noqa: F401


def test_context_constructor_applies_excludes(tmp_path):
    """Excludes passed to the constructor filter discovery from the start."""
    skill = tmp_path / "templates" / "my-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: my-skill\ndescription: x\n---\nBody\n")
    kept = tmp_path / "kept-skill"
    kept.mkdir()
    (kept / "SKILL.md").write_text("---\nname: kept-skill\ndescription: x\n---\nBody\n")

    context = RepositoryContext(tmp_path, exclude_patterns=["templates/**"])
    skill_names = {p.name for p in context.skills}
    assert "kept-skill" in skill_names
    assert "my-skill" not in skill_names


def test_context_constructor_excludes_precede_format_detection(tmp_path):
    """Excluded instruction files must not drive format detection."""
    from skillsaw.context import HAS_COPILOT

    vendored = tmp_path / "vendor"
    vendored.mkdir()
    (vendored / "coding.instructions.md").write_text("Vendored instructions\n")

    context = RepositoryContext(tmp_path, exclude_patterns=["vendor/**"])
    assert not context.instruction_files
    assert HAS_COPILOT not in context.detected_formats

    unfiltered = RepositoryContext(tmp_path)
    assert HAS_COPILOT in unfiltered.detected_formats


def test_severity_enum_matches():
    # default_severity() must return a Severity for every rule
    for cls in BUILTIN_RULES:
        assert isinstance(cls().default_severity(), Severity)
