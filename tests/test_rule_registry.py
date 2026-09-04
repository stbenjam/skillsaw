"""Tests for the auto-discovered builtin rule registry.

The registry (``skillsaw.rules.builtin``) walks the package for concrete
``Rule`` subclasses; ``LinterConfig.default()`` is generated from it. These
tests guard the invariants that made the old hand-maintained lists drift.
"""

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import LintTarget
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
    assert list(BUILTIN_RULE_REGISTRY.values()) == BUILTIN_RULES


def test_registry_classes_are_concrete_rules():
    for cls in BUILTIN_RULES:
        assert issubclass(cls, Rule)
        rule = cls()  # must be instantiable with no config
        assert rule.rule_id
        assert rule.description


def test_new_rules_are_not_force_enabled():
    """Project policy: a rule that ships after 0.20.0 defaults to ``auto``
    or ``False``, never ``True``.

    ``default_enabled = True`` runs the rule in every repository the day a
    user upgrades, whether or not it has anything the rule can read. ``auto``
    with ``repo_types`` is how a rule says where it applies.
    """
    offenders = [
        cls.__name__
        for cls in BUILTIN_RULES
        if _version(cls.since) >= (0, 20, 0) and cls.default_enabled not in ("auto", False)
    ]
    assert offenders == [], (
        f"{offenders} default to enabled: true — declare repo_types "
        "and leave default_enabled at 'auto', or set it to False for opt-in"
    )


def test_class_import_aliases_do_not_duplicate_a_rule():
    """Renamed rules keep their old class name importable (0.18.0's
    ``claude-*`` renames set the precedent, and ``HooksJsonValidRule`` follows
    it). Discovery dedupes by class identity, so a second binding must not
    become a second registry entry."""
    from skillsaw.rules.builtin.hooks import ClaudeHooksValidRule, HooksJsonValidRule

    assert HooksJsonValidRule is ClaudeHooksValidRule
    assert [cls for cls in BUILTIN_RULES if cls is ClaudeHooksValidRule] == [ClaudeHooksValidRule]


def _version(text):
    parts = (text or "0.1.0").split(".")
    return tuple(int(part) for part in parts[:3])


def test_default_enabled_values_are_valid():
    for cls in BUILTIN_RULES:
        assert cls.default_enabled in (True, False, "auto"), (
            f"{cls.__name__}.default_enabled must be True, False, or 'auto', "
            f"got {cls.default_enabled!r}"
        )


@pytest.mark.parametrize("attribute", ["target_dependencies", "surface_dependencies"])
def test_rule_dependencies_are_known_builtins(attribute):
    problems = []
    known = set(BUILTIN_RULE_REGISTRY)
    for rule_id, cls in BUILTIN_RULE_REGISTRY.items():
        unknown = set(getattr(cls, attribute)) - known
        if unknown:
            problems.append(f"{rule_id}: {', '.join(sorted(unknown))}")
    assert problems == [], f"unknown {attribute.replace('_', ' ')}: {problems}"


def test_target_dependencies_declare_lint_target_scopes():
    problems = []
    for rule_id, cls in BUILTIN_RULE_REGISTRY.items():
        dependencies = set(cls.target_dependencies)
        scopes = cls.target_dependency_scopes
        if set(scopes) != dependencies:
            problems.append(f"{rule_id}: scope keys must match target dependencies")
            continue
        for dependency, target_types in scopes.items():
            if not isinstance(target_types, tuple) or not target_types:
                problems.append(f"{rule_id} -> {dependency}: scope must be a non-empty tuple")
                continue
            if not all(
                isinstance(target_type, type) and issubclass(target_type, LintTarget)
                for target_type in target_types
            ):
                problems.append(f"{rule_id} -> {dependency}: scope contains a non-target type")
    assert problems == [], f"invalid target dependency scopes: {problems}"


def test_target_dependencies_do_not_form_chains():
    dependency_ids = {
        dependency
        for cls in BUILTIN_RULE_REGISTRY.values()
        for dependency in cls.target_dependencies
    }
    chained = sorted(
        rule_id for rule_id in dependency_ids if BUILTIN_RULE_REGISTRY[rule_id].target_dependencies
    )
    assert chained == [], (
        "target dependency chains need path-aware scope propagation; "
        f"split these chains before adding them: {chained}"
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


def test_legacy_hooks_rule_class_name_still_imports():
    """0.20.0 renamed ``hooks-json-valid`` to ``claude-hooks-valid`` and
    split Codex's checks out. Third-party code importing the old class name
    keeps working, as it did through the 0.18.0 renames."""
    import skillsaw.rules.builtin as builtin
    from skillsaw.rules.builtin import HooksJsonValidRule as FromRoot
    from skillsaw.rules.builtin.hooks import HooksJsonValidRule
    from skillsaw.rules.builtin.hooks.json_valid import HooksJsonValidRule as FromModule

    assert HooksJsonValidRule is FromModule
    assert FromRoot is FromModule
    assert HooksJsonValidRule().rule_id == "claude-hooks-valid"
    assert (
        "HooksJsonValidRule"
        in __import__("skillsaw.rules.builtin.hooks", fromlist=["__all__"]).__all__
    )
    # The root exporter keys on ``cls.__name__``, which a rename leaves on the
    # new name — the legacy name has to reach ``__all__`` from its own map.
    assert "HooksJsonValidRule" in builtin.__all__
    assert [rid for rid, cls in BUILTIN_RULE_REGISTRY.items() if cls is FromRoot] == [
        "claude-hooks-valid"
    ]
    with pytest.raises(AttributeError):
        builtin.NoSuchLegacyRule


def test_no_builtin_rule_declares_a_formats_attribute():
    """0.20.0 folded the ``HAS_*`` format labels into ``RepositoryType``, so
    a rule now gates on ``repo_types`` alone.

    Nothing reads ``formats`` any more. A rule class that still declared one
    would look gated and be ungated — the silent no-op this suite exists to
    catch — so the removal is pinned rather than trusted.
    """
    offenders = [cls.__name__ for cls in BUILTIN_RULES if hasattr(cls, "formats")]

    assert offenders == [], (
        f"{offenders} still declare a 'formats' attribute; gate on repo_types "
        "instead — nothing reads formats"
    )


def test_every_detected_tool_type_is_listed_in_tool_repo_types(tmp_path):
    """``TOOL_REPO_TYPES`` is what ``_refresh_tool_types`` recomputes.

    A tool type detection can produce but that set omits would be added once
    at construction and never refreshed — it would survive an exclude that
    removed its marker, and it would not be unioned back in under a
    ``--type`` override.
    """
    from skillsaw.context import RepositoryType
    from skillsaw.discovery.detect import tool_types
    from skillsaw.repository_types import TOOL_REPO_TYPES

    (tmp_path / ".cursor" / "rules").mkdir(parents=True)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "copilot-instructions.md").write_text("Use tabs in Makefiles.\n")
    (tmp_path / ".clinerules").write_text("Prefer small commits.\n")
    (tmp_path / ".devin" / "rules").mkdir(parents=True)
    (tmp_path / "opencode.json").write_text('{"$schema": "https://opencode.ai/config.json"}\n')
    (tmp_path / ".muse").mkdir()
    (tmp_path / ".muse" / "hooks.json").write_text('{"hooks": {}}\n')
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "hooks.json").write_text('{"hooks": {}}\n')
    (tmp_path / ".grok" / "hooks").mkdir(parents=True)
    (tmp_path / ".grok" / "hooks" / "session-start.json").write_text('{"hooks": {}}\n')
    (tmp_path / ".kiro").mkdir()
    (tmp_path / "GEMINI.md").write_text("# Gemini\n\nRun `make test`.\n")
    (tmp_path / "QWEN.md").write_text("# Qwen\n\nRun `make test`.\n")
    (tmp_path / ".agents").mkdir(exist_ok=True)
    (tmp_path / ".agents" / "hooks.json").write_text('{"lint": {"Stop": []}}\n')
    (tmp_path / "AGENTS.md").write_text("# Agents\n\nRun `make test`.\n")
    (tmp_path / "CLAUDE.md").write_text("# Claude\n\nRun `make test`.\n")
    (tmp_path / ".coderabbit.yaml").write_text("reviews:\n  profile: chill\n")
    (tmp_path / "skills-lock.json").write_text('{"skills": {}}\n')

    context = RepositoryContext(tmp_path)
    scan = context._repository_scan()
    # ``RepositoryType(value)`` raises on a value the enum does not have, so
    # the conversion itself pins detection to the vocabulary.
    detected = {
        RepositoryType(value)
        for value in tool_types(
            tmp_path,
            context.instruction_files,
            context.is_path_excluded,
            scan.tool_dirs,
            scan.legacy_editor_files,
            scan.skills_lock_files,
        )
    }

    assert detected <= TOOL_REPO_TYPES, sorted(t.value for t in detected - TOOL_REPO_TYPES)
    # The fixture carries one marker per tool, so the two sets should meet:
    # a member here that detection never produces is a type nothing can set.
    assert detected == TOOL_REPO_TYPES, sorted(t.value for t in TOOL_REPO_TYPES - detected)


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


def test_context_constructor_excludes_precede_tool_detection(tmp_path):
    """Excluded instruction files must not drive tool detection."""
    from skillsaw.context import RepositoryType

    vendored = tmp_path / "vendor"
    vendored.mkdir()
    (vendored / "coding.instructions.md").write_text("Vendored instructions\n")

    context = RepositoryContext(tmp_path, exclude_patterns=["vendor/**"])
    assert not context.instruction_files
    assert RepositoryType.COPILOT not in context.repo_types

    unfiltered = RepositoryContext(tmp_path)
    assert RepositoryType.COPILOT in unfiltered.repo_types


def test_excluded_root_marker_does_not_set_a_repo_type(tmp_path):
    """Excluded root marker files must not add a tool repository type."""
    from skillsaw.context import RepositoryType

    (tmp_path / "CLAUDE.md").write_text("# Project instructions\n")

    context = RepositoryContext(tmp_path, exclude_patterns=["CLAUDE.md"])
    assert RepositoryType.CLAUDE_MD not in context.repo_types

    unfiltered = RepositoryContext(tmp_path)
    assert RepositoryType.CLAUDE_MD in unfiltered.repo_types


def test_apply_excludes_refreshes_the_tool_repo_types(tmp_path):
    """Legacy callers mutating exclude_patterns get recomputed types.

    The last marker going away leaves nothing detected, so the repository
    falls back to ``unknown`` rather than keeping a type it no longer has.
    """
    from skillsaw.context import RepositoryType

    (tmp_path / "CLAUDE.md").write_text("# Project instructions\n")

    context = RepositoryContext(tmp_path)
    assert RepositoryType.CLAUDE_MD in context.repo_types

    context.exclude_patterns = ["CLAUDE.md"]
    context.apply_excludes()
    assert RepositoryType.CLAUDE_MD not in context.repo_types
    assert context.repo_types == {RepositoryType.UNKNOWN}
    assert not context.instruction_files


def test_an_explicit_type_override_survives_apply_excludes(tmp_path):
    """``--type`` is the operator's answer; detection never takes it away.

    Detection still adds to it: the override answers how the content is
    packaged, not which tools the checkout configures, so the CLAUDE.md here
    contributes its own type alongside the forced one.
    """
    from skillsaw.context import RepositoryType

    (tmp_path / "CLAUDE.md").write_text("# Project instructions\n")

    context = RepositoryContext(tmp_path, repo_types={RepositoryType.MUSE})
    context.apply_excludes()

    assert {RepositoryType.MUSE} <= context.repo_types
    assert RepositoryType.CLAUDE_MD in context.repo_types


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


def _mcp_config_role_subclasses():
    """Every ``McpConfigRole`` subclass, with the block modules imported."""
    import skillsaw.lint_tree  # noqa: F401  (imports every block module)
    from skillsaw.blocks import McpConfigRole

    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    return list(walk(McpConfigRole))


def test_every_surface_rule_is_a_declared_dependency_of_mcp_valid_json():
    """``mcp-valid-json`` gates on *every* ``surface_rule``, deferral or not.

    A block whose rule is not in ``surface_dependencies`` reads as gated
    off, and the shape walk is skipped silently. Same for a ``syntax_error_rule``: the
    parse finding is handed back only when that rule is known to be off,
    and an undeclared one always looks off.
    """
    from skillsaw.rules.builtin.mcp.valid_json import McpValidJsonRule

    subs = _mcp_config_role_subclasses()
    declared = set(McpValidJsonRule.surface_dependencies)
    surfaces = {sub.surface_rule for sub in subs if sub.surface_rule is not None}
    owners = {
        sub.shape_deferral.syntax_error_rule
        for sub in subs
        if sub.shape_deferral is not None and sub.shape_deferral.syntax_error_rule is not None
    }

    assert surfaces, "no block declares a surface_rule — the walk found nothing"
    assert owners, "no block declares a syntax_error_rule — the walk found nothing"
    assert sorted(surfaces - declared) == []
    assert sorted(owners - declared) == []
