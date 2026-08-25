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
    assert "claude-plugin-json-required" in ids
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
    active = {rid for rid, cls in BUILTIN_RULE_REGISTRY.items() if cls.deprecated is None}
    # Deprecated rules are deliberately left out of generated configs.
    assert set(defaults) == active
    for rule_id in active:
        cls = BUILTIN_RULE_REGISTRY[rule_id]
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


def test_excluded_root_marker_does_not_set_format(tmp_path):
    """Excluded root marker files must not flip format flags."""
    from skillsaw.context import HAS_CLAUDE_MD

    (tmp_path / "CLAUDE.md").write_text("# Project instructions\n")

    context = RepositoryContext(tmp_path, exclude_patterns=["CLAUDE.md"])
    assert HAS_CLAUDE_MD not in context.detected_formats

    unfiltered = RepositoryContext(tmp_path)
    assert HAS_CLAUDE_MD in unfiltered.detected_formats


def test_apply_excludes_refreshes_detected_formats(tmp_path):
    """Legacy callers mutating exclude_patterns get recomputed formats."""
    from skillsaw.context import HAS_CLAUDE_MD

    (tmp_path / "CLAUDE.md").write_text("# Project instructions\n")

    context = RepositoryContext(tmp_path)
    assert HAS_CLAUDE_MD in context.detected_formats

    context.exclude_patterns = ["CLAUDE.md"]
    context.apply_excludes()
    assert HAS_CLAUDE_MD not in context.detected_formats
    assert not context.instruction_files


def test_severity_enum_matches():
    # default_severity() must return a Severity for every rule
    for cls in BUILTIN_RULES:
        assert isinstance(cls().default_severity(), Severity)


def test_every_rule_since_is_not_in_the_future():
    """A rule whose ``since`` postdates the shipped version is silently dead
    for every version-pinning user — unit tests call check() directly and
    bypass config gating, so nothing else catches this class."""
    from skillsaw import __version__
    from skillsaw.config import _parse_version
    from skillsaw.rules.builtin import BUILTIN_RULES

    current = _parse_version(__version__)
    future = [cls().rule_id for cls in BUILTIN_RULES if _parse_version(cls.since) > current]
    assert not future, f"rules gated behind a future version: {future}"


def test_builtin_config_schema_entries_have_complete_shape():
    problems = []
    required = {"type", "default", "description"}
    for rule_id, rule_cls in BUILTIN_RULE_REGISTRY.items():
        for option, entry in rule_cls.config_schema.items():
            if not isinstance(entry, dict) or not required.issubset(entry):
                problems.append(f"{rule_id}.{option}")
    assert problems == [], f"malformed config_schema entries: {problems}"


def test_config_reads_are_declared_in_config_schema():
    """Every self.config read in a builtin rule must name a declared option.

    Option validation (Linter._option_violations) warns on any config key
    outside a rule's config_schema plus the universal keys — so a rule that
    reads an undeclared key would make its own documented option a false
    "unknown option" warning for users. This pins the zero-drift invariant
    and the house rule "declare config_schema when the rule accepts
    parameters".

    Limitation: inspect.getsource() sees only each concrete class body, not
    inherited reads. Within that body, the scan sees only string literals
    passed directly to self.config.get()/[]/self.setting(). Keys flowing through wrapper
    helpers (e.g. _int_config in security/encoded_payload.py or
    _parse_patterns in content/missing_stop_condition.py) are covered only
    via the literal arguments at their call sites; a wrapper fed a computed
    key is invisible to this guard.
    """
    import ast
    import inspect
    import textwrap

    from skillsaw.linter import UNIVERSAL_RULE_OPTION_KEYS

    problems = []
    for rule_id, rule_cls in BUILTIN_RULE_REGISTRY.items():
        allowed = set(rule_cls.config_schema) | set(UNIVERSAL_RULE_OPTION_KEYS)
        tree = ast.parse(textwrap.dedent(inspect.getsource(rule_cls)))
        for node in ast.walk(tree):
            key = None
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "config"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                key = node.args[0].value
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "config"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                key = node.slice.value
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setting"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                key = node.args[0].value
            if key is not None and key not in allowed:
                problems.append(f"{rule_id}: reads undeclared config key '{key}'")

    assert problems == [], "\n".join(problems)
