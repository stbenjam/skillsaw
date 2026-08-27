"""
Main linter orchestration
"""

from __future__ import annotations

import difflib
import hashlib
import importlib.util
import inspect
import logging
import re
import sys
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING
from skillsaw.paths import safe_is_symlink, safe_resolve

logger = logging.getLogger(__name__)

from .rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from .context import RepositoryContext
from .config import LinterConfig
from .suppression import build_suppression_map_for_file, SuppressionMap
from .utils import mkdir_parents_anchored, rename_path_anchored, write_text_preserving

if TYPE_CHECKING:
    from .baseline import BaselineFile, BaselineEntry


# Violations that display like warnings but never flip the exit code.
# Deprecation notices must stay advisory: every pre-0.18 `skillsaw init`
# config names now-deprecated rules, so a fatal warning would break every
# strict-mode CI run on upgrade.
ADVISORY_RULE_IDS = frozenset({"deprecated-rule"})

# Violations exempt from path-based suppression (global and per-rule
# excludes). Config-validation warnings point at the config file itself;
# excludes select lint targets, and the config's own content must not
# decide whether the config gets validated — `exclude: ["*.yaml"]` would
# otherwise silently drop every unknown-rule/unknown-option warning.
# Inline suppression stays available, but only in its precise form: a
# `# skillsaw-disable-next-line` naming the rule ID — a deliberate,
# visible edit at the exact line the warning names. Region `disable`
# forms and bare all-rules directives are the same blanket this set
# exists to close.
_UNEXCLUDABLE_RULE_IDS = frozenset({"invalid-config"})

# Config keys every rule accepts regardless of its config_schema. `enabled`
# is validated at config load, `severity` at rule construction, and `exclude`
# is read by the linter's per-rule exclude filter.
UNIVERSAL_RULE_OPTION_KEYS = frozenset({"enabled", "severity", "exclude"})

# config_schema `type` strings and the Python types a user value must have.
# `float` accepts int (YAML `4` for a threshold), never bool — bool is a
# subclass of int, so int/float checks reject it explicitly below.
_OPTION_TYPE_MAP: Dict[str, Any] = {
    "list": list,
    "array": list,
    "int": int,
    "integer": int,
    "float": (int, float),
    "number": (int, float),
    "bool": bool,
    "boolean": bool,
    "dict": dict,
    "object": dict,
    "str": str,
    "string": str,
}

# The security/supply-chain surface. Not a suppression gate — every one of
# these fires on a compiled copy because none is a prose-duplicate rule (see
# ``_is_prose_duplicate_rule``). Enumerated here so ``test_content_suppression``
# can pin that the security surface stays disjoint from what suppression drops:
# a security rule that ever started being suppressed on compiled copies is how
# a hand-edited compiled file would hide a payload from the whole scan.
SECURITY_RULE_IDS = frozenset(
    {
        "security-dynamic-context",
        "security-encoded-payload",
        "security-hidden-instructions",
        "security-invisible-unicode",
        "hooks-dangerous",
        "hooks-prohibited",
        "mcp-prohibited",
        "claude-settings-dangerous",
        # A ``content-`` rule by id, but a secret scanner by purpose: a
        # credential in the artifact that ships is real even when it echoes the
        # source, and compilation or a hand-edit can introduce one the source
        # never had. Listed here so the prose-duplicate predicate never drops
        # it on a compiled copy.
        "content-embedded-secrets",
    }
)


def _is_prose_duplicate_rule(rule_id: str) -> bool:
    """Whether *rule_id*'s findings on a compiled copy merely echo its source.

    A file APM compiles into an editor location (``.github/``, ``.cursor/``)
    carries the same prose as its ``.apm/`` source, so prose-quality findings
    (``content-*``) and the token budget double what the source already
    reports — those are dropped on the copy. Everything else stays: a
    structural-validity rule checks the compiled artifact's *own* shape
    (a compiled ``.mdc``'s frontmatter, an import that only resolves after
    compilation, the MCP JSON layout) which has no equivalent on the source,
    and every security rule fires on what actually ships. Suppressing those
    was over-broad — it hid unique, real findings on the compiled file.

    Naming the *narrow* set to drop (rather than an allowlist to keep) fails
    toward reporting: a prose rule that ever falls outside this predicate
    merely double-reports, it never hides a structural or security defect.

    A security rule is never a prose duplicate even when its id starts with
    ``content-`` (``content-embedded-secrets`` scans for credentials): the
    ``SECURITY_RULE_IDS`` guard keeps it firing on the artifact that ships.
    """
    if rule_id in SECURITY_RULE_IDS:
        return False
    return rule_id.startswith("content-") or rule_id == "context-budget"


def _node_content_suppressed(block) -> bool:
    """Whether *block* or any ancestor is a compiled-copy node.

    A content violation attaches to a body/field child, so the flag set on
    the attached container is read by walking parents (populated by
    ``set_parents()`` after the tree is built).
    """
    getter = getattr(block, "in_suppressed_content", None)
    if getter is not None:
        return bool(getter)
    # A rule may report against a freshly built ``FileContentBlock`` keyed
    # only by path (``self.violation(file_path=...)``); it has no parent
    # chain, so it is never in suppressed content by this route — the
    # linter's path-based check catches those.
    return False


class CustomRuleWarning(UserWarning):
    """Emitted just before skillsaw executes a custom rule file from the repo.

    Carries ``path`` so the CLI can render the notice as a readable colored
    line instead of the stock ``warnings`` traceback format; library callers
    still get a normal ``UserWarning`` they can filter.
    """

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"Loading custom rule file: {path} — use --no-custom-rules to skip")


class Linter:
    """
    Main linter that orchestrates rule checking
    """

    def __init__(
        self,
        context: RepositoryContext,
        config: LinterConfig = None,
        rule_ids: Optional[Set[str]] = None,
        skip_rule_ids: Optional[Set[str]] = None,
        baseline: Optional["BaselineFile"] = None,
        no_custom_rules: bool = False,
        no_plugins: bool = False,
    ):
        from .rules.builtin import canonical_rule_id

        self.context = context
        self.config = config or LinterConfig.default()
        # Legacy rule names keep working on the CLI: resolve --rule /
        # --skip-rule arguments to canonical IDs before any matching.
        self._rule_ids = {canonical_rule_id(r) for r in rule_ids} if rule_ids else rule_ids
        self._skip_rule_ids = {canonical_rule_id(r) for r in (skip_rule_ids or set())}
        self._baseline = baseline
        self._no_custom_rules = no_custom_rules
        self._no_plugins = no_plugins
        self._plugin_load_violations: List[RuleViolation] = []
        self._vendor_managed_cache: Dict[Path, bool] = {}
        self._stale_baseline_entries: List["BaselineEntry"] = []
        self._baseline_suppressed_count: int = 0
        # Prefer contexts constructed with the config's filters (see
        # RepositoryContext.__init__); only reconfigure when a legacy caller
        # passed a bare context that disagrees with the config.
        # apply_excludes() refreshes derived state (detected_formats, cached
        # lint tree), so this path cannot leave the context stale — but it
        # only narrows: it won't rediscover paths an earlier filter removed.
        if (
            self.context.content_paths != self.config.content_paths
            or self.context.exclude_patterns != self.config.exclude_patterns
        ):
            self.context.content_paths = self.config.content_paths
            self.context.exclude_patterns = self.config.exclude_patterns
            self.context.apply_excludes()
        self.rules: List[Rule] = []
        self._load_rules()

        if self._rule_ids:
            unknown = self._rule_ids - self._known_rule_ids
            if unknown:
                formatted = ", ".join(sorted(unknown))
                raise ValueError(f"Unknown rule(s): {formatted}")

        # A typo in --skip-rule must not silently leave the rule running.
        if self._skip_rule_ids:
            unknown = self._skip_rule_ids - self._known_rule_ids
            if unknown:
                formatted = ", ".join(sorted(unknown))
                raise ValueError(f"Unknown rule(s) in --skip-rule: {formatted}")

    def _load_rules(self):
        """Load all enabled rules"""
        self._known_rule_ids: set = set()
        self._known_rule_classes: Dict[str, type[Rule]] = {}
        self._builtin_rule_ids: set = set()
        self._custom_rule_ids: set = set()
        # Deprecated non-builtin rules seen during loading, kept so a config
        # entry that names one still gets its deprecation notice even when
        # the rule itself no longer runs (builtins are covered by the
        # registry).
        self._deprecated_known: Dict[str, Rule] = {}

        # Load builtin rules
        self._load_builtin_rules()

        if not self._no_plugins and self.config.plugins_enabled:
            self._load_plugin_rules()

        if not self._no_custom_rules:
            for custom_rule_path in self.config.custom_rules:
                self._load_custom_rule(custom_rule_path)

    def _load_builtin_rules(self):
        """Load builtin rules from skillsaw.rules.builtin"""
        from .rules.builtin import BUILTIN_RULES

        for rule_class in BUILTIN_RULES:
            rule_instance = rule_class()
            rid = rule_instance.rule_id
            self._known_rule_ids.add(rid)
            self._known_rule_classes[rid] = rule_class
            self._builtin_rule_ids.add(rid)
            if self._rule_ids and rule_instance.rule_id not in self._rule_ids:
                continue
            if rule_instance.rule_id in self._skip_rule_ids:
                logger.info("Rule %-30s skipped (--skip-rule)", rule_instance.rule_id)
                continue
            config = self.config.get_rule_config(rule_instance.rule_id)
            if config:
                rule_instance = rule_class(config)

            if self._rule_ids or self.config.is_rule_enabled(
                rule_instance.rule_id,
                self.context,
                rule_instance.repo_types,
                rule_instance.formats,
                since_version=rule_instance.since,
                deprecated=rule_instance.deprecated,
            ):
                self.rules.append(rule_instance)
                logger.info("Rule %-30s enabled", rule_instance.rule_id)
            else:
                logger.info("Rule %-30s skipped (not applicable)", rule_instance.rule_id)

    def _load_plugin_rules(self):
        """Load rules from installed plugin packages (skillsaw.plugins entry points).

        A broken plugin must not abort the lint — installing a bad package
        would otherwise brick skillsaw for every repo on the machine.  Load
        failures become ``plugin-load-error`` violations instead, so they
        are visible (and, for errors, affect the exit code) while remaining
        recoverable via ``--no-plugins`` or ``plugins.disable`` in config.
        """
        from .plugins import load_plugins

        plugins = load_plugins(disabled=set(self.config.disabled_plugins))

        # Extensions (repo types, tree contributors) must register before any
        # rule's enablement is evaluated: a plugin rule scoped to its own
        # plugin's repo type needs the detector to have run already.
        self._register_plugin_extensions(plugins)

        for plugin in plugins:
            if plugin.error:
                self._plugin_load_violations.append(
                    RuleViolation(
                        rule_id="plugin-load-error",
                        severity=Severity.ERROR,
                        message=(
                            f"Plugin '{plugin.name}' ({plugin.source}) failed to load: "
                            f"{plugin.error}. Uninstall the package, or skip it with "
                            f"--no-plugins or 'plugins: {{disable: [{plugin.name}]}}' "
                            "in .skillsaw.yaml."
                        ),
                    )
                )
                continue

            for rule_class in plugin.rule_classes:
                try:
                    rule_instance = rule_class()
                    # rule_id is a plugin-controlled property: a raising
                    # implementation must be fault-isolated exactly like a
                    # failing constructor, or one bad plugin aborts the lint.
                    rid = rule_instance.rule_id
                except Exception as e:
                    self._plugin_load_violations.append(
                        RuleViolation(
                            rule_id="plugin-load-error",
                            severity=Severity.ERROR,
                            message=(
                                f"Plugin '{plugin.name}': rule class "
                                f"{rule_class.__name__} could not be loaded: "
                                f"{e.__class__.__name__}: {e}"
                            ),
                        )
                    )
                    continue

                if rid in self._known_rule_ids:
                    # First loader wins (builtins, then earlier plugins); a
                    # shadowing rule would silently change what a rule ID means.
                    self._plugin_load_violations.append(
                        RuleViolation(
                            rule_id="plugin-load-error",
                            severity=Severity.WARNING,
                            message=(
                                f"Plugin '{plugin.name}' provides rule '{rid}', which "
                                "already exists — the plugin's version was skipped. "
                                "Plugin rule IDs must not collide with builtin rules "
                                "or other plugins."
                            ),
                        )
                    )
                    continue

                # Legacy aliases still resolve to their builtin everywhere a
                # rule is named (config keys, flags, suppressions), so a
                # plugin claiming one could never be addressed under its own
                # name. Advisory IDs are reserved for skillsaw's own notices
                # — a rule reporting under one would never affect the exit
                # code.
                from .rules.builtin import RULE_ALIASES

                if rid in RULE_ALIASES or rid in ADVISORY_RULE_IDS:
                    reason = (
                        f"'{rid}' is a legacy alias of builtin rule '{RULE_ALIASES[rid]}'"
                        if rid in RULE_ALIASES
                        else f"'{rid}' is reserved for skillsaw's own advisory notices"
                    )
                    self._plugin_load_violations.append(
                        RuleViolation(
                            rule_id="plugin-load-error",
                            severity=Severity.WARNING,
                            message=(
                                f"Plugin '{plugin.name}' provides rule '{rid}', but "
                                f"{reason} — the plugin's rule was skipped."
                            ),
                        )
                    )
                    continue

                self._known_rule_ids.add(rid)
                self._known_rule_classes[rid] = rule_class
                if getattr(rule_instance, "deprecated", None) is not None:
                    self._deprecated_known[rid] = rule_instance
                if self._rule_ids and rid not in self._rule_ids:
                    continue
                if rid in self._skip_rule_ids:
                    logger.info("Rule %-30s skipped (--skip-rule, plugin: %s)", rid, plugin.name)
                    continue
                config = self.config.get_rule_config(rid)
                if config:
                    try:
                        rule_instance = rule_class(config)
                    except Exception as e:
                        self._plugin_load_violations.append(
                            RuleViolation(
                                rule_id="plugin-load-error",
                                severity=Severity.ERROR,
                                message=(
                                    f"Plugin '{plugin.name}': rule '{rid}' rejected its "
                                    f"configuration: {e.__class__.__name__}: {e}"
                                ),
                            )
                        )
                        continue

                # Plugin rules have no entry in the builtin registry that
                # LinterConfig.default() is generated from, so their
                # class-level default (Rule.default_enabled — True, False,
                # or "auto") is supplied directly. Semantics match builtins:
                # "auto" follows repo_types/formats detection, False is
                # opt-in via config.
                try:
                    # repo_types/formats/since/default_enabled are read from
                    # the plugin's class here — same fault isolation as above.
                    enabled = bool(self._rule_ids) or self.config.is_rule_enabled(
                        rid,
                        self.context,
                        rule_instance.repo_types,
                        rule_instance.formats,
                        since_version=rule_instance.since,
                        default_enabled=rule_instance.default_enabled,
                        deprecated=rule_instance.deprecated,
                    )
                except Exception as e:
                    self._plugin_load_violations.append(
                        RuleViolation(
                            rule_id="plugin-load-error",
                            severity=Severity.ERROR,
                            message=(
                                f"Plugin '{plugin.name}': rule '{rid}' raised "
                                f"while evaluating enablement: "
                                f"{e.__class__.__name__}: {e}"
                            ),
                        )
                    )
                    continue
                if enabled:
                    rule_instance._source = f"plugin:{plugin.name}"
                    self.rules.append(rule_instance)
                    logger.info("Rule %-30s enabled (plugin: %s)", rid, plugin.name)
                else:
                    logger.info("Rule %-30s skipped (plugin: %s)", rid, plugin.name)

    def _register_plugin_extensions(self, plugins) -> None:
        """Register plugin-declared repo types and lint tree contributors.

        Delegates to :func:`skillsaw.plugins.register_extensions` (shared
        with the ``tree`` and ``explain`` commands) and maps the problems it
        reports to ``plugin-load-error`` violations: crashed detectors are
        errors, skipped duplicate/builtin-colliding declarations warnings.
        """
        from .plugins import register_extensions

        for problem in register_extensions(self.context, plugins):
            self._plugin_load_violations.append(
                RuleViolation(
                    rule_id="plugin-load-error",
                    severity=Severity.ERROR if problem.severity == "error" else Severity.WARNING,
                    message=problem.message,
                )
            )

    def _plugin_extension_error_violations(self) -> List[RuleViolation]:
        """Violations for tree-contributor failures collected during tree build.

        Contributors run inside ``build_lint_tree`` (lazily, on first tree
        access), so their errors surface after the rule loop rather than at
        load time. Consumes the collected errors so repeated runs on the same
        Linter don't duplicate them.
        """
        errors = self.context.plugin_extension_errors
        self.context.plugin_extension_errors = []
        return [
            RuleViolation(
                rule_id="plugin-load-error",
                severity=Severity.ERROR,
                message=message,
            )
            for message in errors
        ]

    def _lint_tree_error_violations(self) -> List[RuleViolation]:
        """Translate persistent repository discovery errors into violations."""
        errors = dict.fromkeys(self.context.lint_tree_errors)
        return [
            RuleViolation(
                rule_id="repository-path-error",
                severity=Severity.ERROR,
                message=message,
            )
            for message in errors
        ]

    def _load_custom_rule(self, rule_path: str):
        """
        Load a custom rule from a Python file

        Args:
            rule_path: Path to Python file containing Rule subclass
        """
        path = Path(rule_path)
        if not path.is_absolute():
            base = self.config.config_dir or self.context.root_path
            path = base / path
        unresolved_path = path
        path = safe_resolve(path)
        if path is None:
            raise ValueError(f"Custom rule path could not be resolved: {unresolved_path}")

        try:
            path.stat()
        except (FileNotFoundError, NotADirectoryError):
            raise ValueError(f"Custom rule file not found: {path}")
        except (OSError, ValueError) as e:
            raise ValueError(f"Custom rule path cannot be accessed: {path}: {e}") from e

        warnings.warn(CustomRuleWarning(path), stacklevel=2)
        logger.info("Loading custom rules from %s", path)

        # Unique module name per file so two custom rule files cannot clobber
        # each other in ``sys.modules`` (they previously all loaded as
        # ``custom_rule``).
        safe_stem = re.sub(r"\W", "_", path.stem)
        path_digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
        module_name = f"skillsaw_custom_{safe_stem}_{path_digest}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            # Register before exec (the documented module_from_spec pattern) so
            # the module is importable by name and rule classes carry a distinct
            # __module__ — this is what keeps two rule files from colliding.
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
        except Exception as e:
            # Surface a friendly error (the CLI catches ValueError) instead of
            # leaking a SyntaxError/ImportError traceback from the rule file.
            raise ValueError(f"Failed to load custom rule from {path}: {e}") from e

        try:
            for name in dir(module):
                obj = getattr(module, name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, Rule)
                    and obj is not Rule
                    and not inspect.isabstract(obj)
                ):
                    rule_instance = obj()

                    # Same reservation as plugin rules: a custom rule named
                    # after a legacy alias could never be addressed (config
                    # keys and flags resolve the alias to the builtin), and
                    # an advisory ID would exempt its findings from the exit
                    # code.
                    from .rules.builtin import RULE_ALIASES

                    rid = rule_instance.rule_id
                    if rid in RULE_ALIASES or rid in ADVISORY_RULE_IDS:
                        reason = (
                            f"'{rid}' is a legacy alias of builtin rule '{RULE_ALIASES[rid]}'"
                            if rid in RULE_ALIASES
                            else f"'{rid}' is reserved for skillsaw's own advisory notices"
                        )
                        self._plugin_load_violations.append(
                            RuleViolation(
                                rule_id="plugin-load-error",
                                severity=Severity.WARNING,
                                message=(
                                    f"Custom rule file {path.name} provides rule '{rid}', "
                                    f"but {reason} — the rule was skipped."
                                ),
                            )
                        )
                        continue

                    self._known_rule_ids.add(rule_instance.rule_id)
                    # On an ID collision the earlier class (builtin or a
                    # prior custom file) keeps validation ownership; only
                    # tag the ID custom when this class actually won, so
                    # the explain hint agrees with the schema used.
                    if self._known_rule_classes.setdefault(rule_instance.rule_id, obj) is obj:
                        self._custom_rule_ids.add(rule_instance.rule_id)
                    if getattr(rule_instance, "deprecated", None) is not None:
                        self._deprecated_known[rule_instance.rule_id] = rule_instance
                    if self._rule_ids and rule_instance.rule_id not in self._rule_ids:
                        continue
                    if rule_instance.rule_id in self._skip_rule_ids:
                        logger.info(
                            "Rule %-30s skipped (--skip-rule, custom: %s)",
                            rule_instance.rule_id,
                            path.name,
                        )
                        continue
                    config = self.config.get_rule_config(rule_instance.rule_id)
                    if config:
                        rule_instance = obj(config)

                    if self._rule_ids or self.config.is_rule_enabled(
                        rule_instance.rule_id,
                        self.context,
                        rule_instance.repo_types,
                        rule_instance.formats,
                        since_version=rule_instance.since,
                        deprecated=rule_instance.deprecated,
                    ):
                        rule_instance._source = "custom"
                        self.rules.append(rule_instance)
                        logger.info(
                            "Rule %-30s enabled (custom: %s)",
                            rule_instance.rule_id,
                            path.name,
                        )
                    else:
                        logger.info(
                            "Rule %-30s skipped (custom: %s)",
                            rule_instance.rule_id,
                            path.name,
                        )
        except Exception as e:
            raise ValueError(f"Failed to load custom rule from {path}: {e}") from e

    def _validate_config(self) -> List[RuleViolation]:
        """Check for unknown rule IDs in config"""
        # With --no-custom-rules, IDs supplied by unloaded custom rule files
        # are unknowable without executing them — exactly what the flag
        # forbids. Don't flag config entries as typos in that case.
        skip_unknown = self._no_custom_rules and bool(self.config.custom_rules)
        # Same reasoning when installed plugins were skipped (--no-plugins or
        # config): their rule IDs are unknowable without loading them.
        if not skip_unknown and (
            self._no_plugins or not self.config.plugins_enabled or self.config.disabled_plugins
        ):
            from .plugins import installed_plugin_names

            skip_unknown = bool(installed_plugin_names())
        warnings = list(self._plugin_load_violations)
        warnings.extend(self._deprecation_violations())
        for rule_id in self.config.rules:
            if rule_id not in self._known_rule_ids:
                if skip_unknown:
                    logger.info(
                        "Rule %-30s unknown in config; may be a custom rule "
                        "(skipped due to --no-custom-rules)",
                        rule_id,
                    )
                    continue
                warnings.append(
                    RuleViolation(
                        rule_id="invalid-config",
                        severity=Severity.WARNING,
                        message=f"Unknown rule '{rule_id}' in config — rule does not exist and will be ignored",
                        file_path=self.config.config_path,
                        line=self.config.config_rule_lines.get(rule_id),
                        fingerprint_discriminator=f"unknown-rule:{rule_id}",
                    )
                )
                continue
            warnings.extend(self._option_violations(rule_id, self.config.rules[rule_id]))
        return warnings

    def _option_violations(self, rule_id: str, overrides: Dict[Any, Any]) -> List[RuleViolation]:
        """Validate one configured rule's option keys against its config_schema.

        Schema resolution is enablement-independent, like the unknown-rule-ID
        check above: a typo on a disabled or auto-inactive builtin still warns.
        Plugin/custom rules opt in by declaring a config_schema; without one
        their option names are unknowable, so they are skipped. Rule classes
        are recorded at load time, so validation does not depend on whether a
        rule is enabled for this repository.
        """
        if not isinstance(overrides, dict):
            return []
        rule_class = self._known_rule_classes.get(rule_id)
        if rule_class is None:
            return []
        try:
            schema = getattr(rule_class, "config_schema", {}) or {}
            if not isinstance(schema, dict):
                # A malformed third-party schema (e.g. a list of option names)
                # must not abort the lint — treat it as undeclared.
                schema = {}
            else:
                # Same for non-string schema keys: they can never match a config
                # key and would crash the sorted() feeding did-you-mean.
                # dict(v) detaches entries from third-party dict subclasses,
                # so no overridden method (get, __getitem__) can raise later,
                # outside this guard, mid-validation.
                schema = {
                    k: dict(v) if isinstance(v, dict) else v
                    for k, v in schema.items()
                    if isinstance(k, str)
                }
            # bool() now: a deferred truth test on a third-party object
            # whose __bool__ raises would escape this guard.
            strict_options = bool(getattr(rule_class, "strict_options", True))
        except Exception:
            # Attribute access itself can raise on a third-party class (a
            # descriptor, a dict subclass whose __bool__/items raises).
            # Validation runs outside the fault isolation rule execution
            # gets, so treat the schema as undeclared rather than abort.
            schema = {}
            strict_options = True
        # A schema-less plugin/custom rule leaves its option names
        # unknowable, so unknown-key validation is skipped for it below —
        # but the universal keys are the linter's own contract, and their
        # shape checks still run (`_is_rule_excluded` fails open on a
        # malformed `exclude`, which would otherwise be silent).
        schema_known = bool(schema) or rule_id in self._builtin_rule_ids
        allowed = set(schema) | UNIVERSAL_RULE_OPTION_KEYS

        violations: List[RuleViolation] = []
        for key, value in overrides.items():
            discriminator = f"{rule_id}:{key}"
            line = self.config.config_option_lines.get((rule_id, key))
            if not isinstance(key, str):
                violations.append(
                    RuleViolation(
                        rule_id="invalid-config",
                        severity=Severity.WARNING,
                        message=f"Invalid option key '{key}' for rule '{rule_id}' "
                        "— option keys must be strings (YAML keys like `on:` or "
                        "`1:` parse as non-strings)",
                        file_path=self.config.config_path,
                        line=line,
                        fingerprint_discriminator=discriminator,
                    )
                )
                continue
            if key not in allowed:
                if not schema_known or not strict_options:
                    continue
                # 0.6 intentionally catches common separator/shortening typos
                # such as max-length vs max_length and length vs max_length.
                close = difflib.get_close_matches(key, sorted(allowed), n=1, cutoff=0.6)
                if close:
                    hint = f" (did you mean '{close[0]}'?)"
                elif rule_id in self._custom_rule_ids:
                    hint = ""
                else:
                    hint = f" — run `skillsaw explain {rule_id}` to see valid options"
                violations.append(
                    RuleViolation(
                        rule_id="invalid-config",
                        severity=Severity.WARNING,
                        message=f"Unknown option '{key}' for rule '{rule_id}' "
                        "— it is not valid for this rule; unrecognized keys still "
                        f"count as configuration and may enable an opt-in rule{hint}",
                        file_path=self.config.config_path,
                        line=line,
                        fingerprint_discriminator=discriminator,
                    )
                )
                continue
            if key == "exclude":
                if not isinstance(value, list):
                    actual = "null" if value is None else type(value).__name__
                    violations.append(
                        RuleViolation(
                            rule_id="invalid-config",
                            severity=Severity.WARNING,
                            message=f"Option 'exclude' for rule '{rule_id}' "
                            f"expects list of strings, got {actual}",
                            file_path=self.config.config_path,
                            line=line,
                            fingerprint_discriminator=discriminator,
                        )
                    )
                elif not all(isinstance(pattern, str) for pattern in value):
                    violations.append(
                        RuleViolation(
                            rule_id="invalid-config",
                            severity=Severity.WARNING,
                            message=f"Option 'exclude' for rule '{rule_id}' "
                            "expects list of strings",
                            file_path=self.config.config_path,
                            line=line,
                            fingerprint_discriminator=discriminator,
                        )
                    )
                continue
            entry = schema.get(key)
            if not isinstance(entry, dict):
                # Universal-only key, or a malformed third-party schema entry.
                continue
            entry_type = entry.get("type")
            if not isinstance(entry_type, str):
                # Third-party schemas may use non-string types (e.g. a
                # JSON-Schema-style list) — unknown shapes are not checked.
                continue
            expected = _OPTION_TYPE_MAP.get(entry_type)
            if expected is None:
                continue
            bool_for_number = isinstance(value, bool) and entry_type in (
                "int",
                "integer",
                "float",
                "number",
            )
            if value is None or bool_for_number or not isinstance(value, expected):
                actual = "null" if value is None else type(value).__name__
                violations.append(
                    RuleViolation(
                        rule_id="invalid-config",
                        severity=Severity.WARNING,
                        message=f"Option '{key}' for rule '{rule_id}' "
                        f"expects {entry_type}, got {actual}",
                        file_path=self.config.config_path,
                        line=line,
                        fingerprint_discriminator=discriminator,
                    )
                )
        return violations

    def _deprecation_violations(self) -> List[RuleViolation]:
        """Warnings for deprecated rules the user still runs or configures.

        A deprecated rule that is actually going to run (explicitly enabled
        or forced via --rule) warns that it will be removed in a future
        release. A config entry for a deprecated rule that no longer runs
        warns that the entry is now inert. Each rule warns once.
        """
        from .rules.builtin import BUILTIN_RULE_REGISTRY

        violations: List[RuleViolation] = []
        warned: set = set()

        def _removal_hint(rule) -> str:
            hint = f"deprecated since {rule.deprecated} and will be removed in a future release"
            if getattr(rule, "replaced_by", None):
                hint += f" — use '{rule.replaced_by}' instead"
            return hint

        for rule in self.rules:
            # getattr: tests and duck-typed custom rules may not inherit the
            # class attribute from Rule.
            if getattr(rule, "deprecated", None) is None:
                continue
            warned.add(rule.rule_id)
            violations.append(
                RuleViolation(
                    rule_id="deprecated-rule",
                    severity=Severity.WARNING,
                    message=f"Rule '{rule.rule_id}' is {_removal_hint(rule)}",
                )
            )
        for rule_id in self.config.rules:
            if rule_id in warned:
                continue
            # Builtins come from the registry; deprecated plugin and custom
            # rules were recorded during loading so their inert config
            # entries warn too.
            rule_class = BUILTIN_RULE_REGISTRY.get(rule_id) or self._deprecated_known.get(rule_id)
            if rule_class is None or getattr(rule_class, "deprecated", None) is None:
                continue
            violations.append(
                RuleViolation(
                    rule_id="deprecated-rule",
                    severity=Severity.WARNING,
                    message=(
                        f"Rule '{rule_id}' is {_removal_hint(rule_class)}; it no longer "
                        "runs unless the config sets 'enabled: true' — remove the config "
                        "entry or enable it explicitly"
                    ),
                )
            )
        return violations

    def deprecation_notices(self) -> List[RuleViolation]:
        """Advisory notices for deprecated rules this run touches.

        Public for CLI commands whose output does not include lint
        violations (``skillsaw fix``) so they can still surface the
        promised removal warnings.
        """
        return self._deprecation_violations()

    def _is_excluded(self, violation: RuleViolation) -> bool:
        """Check if a violation's file path matches any exclude pattern."""
        if violation.file_path is None:
            return False
        if violation.rule_id in _UNEXCLUDABLE_RULE_IDS:
            return False
        return self.context.is_path_excluded(violation.file_path)

    def _is_rule_excluded(self, rule_id: str, file_path: Optional[Path]) -> bool:
        """Check if a file path matches a rule's per-rule excludes patterns."""
        if file_path is None:
            return False
        if rule_id in _UNEXCLUDABLE_RULE_IDS:
            return False
        exclude = self.config.get_rule_config(rule_id).get("exclude")
        if not isinstance(exclude, list) or not exclude:
            return False
        if not all(isinstance(pattern, str) for pattern in exclude):
            return False
        return self.context.matches_patterns(file_path, exclude)

    def _get_suppression_map(self, file_path: Path) -> Optional[SuppressionMap]:
        """Get or build a suppression map for a file, with caching."""
        resolved = safe_resolve(file_path) or file_path
        if not hasattr(self, "_suppression_cache"):
            self._suppression_cache: Dict[Path, Optional[SuppressionMap]] = {}
        if resolved not in self._suppression_cache:
            self._suppression_cache[resolved] = build_suppression_map_for_file(resolved)
        return self._suppression_cache[resolved]

    def _is_inline_suppressed(self, violation: RuleViolation) -> bool:
        """Check if a violation is suppressed by an inline directive."""
        if violation.file_path is None:
            return False
        file_line = violation.file_line
        if file_line is None:
            return False
        smap = self._get_suppression_map(violation.file_path)
        if smap is None:
            return False
        if violation.rule_id in _UNEXCLUDABLE_RULE_IDS:
            return smap.is_explicitly_suppressed(violation.rule_id, file_line)
        return smap.is_suppressed(violation.rule_id, file_line)

    def _compiled_copy_paths(self) -> Set[Path]:
        """Resolved paths of every content-suppressed (compiled-copy) file.

        A content rule may report against a freshly built
        ``FileContentBlock`` keyed only by ``file_path`` (context-budget is
        one), so the block has no parent chain to climb. Matching the path
        against this set suppresses those the same way the block-chain check
        suppresses rules that attach the real tree node. Computed once per
        run from the built tree.
        """
        cached = getattr(self, "_compiled_copy_path_cache", None)
        if cached is None:
            cached = {
                node.resolved_path
                for node in self.context.lint_tree.walk()
                if node.content_suppressed
            }
            self._compiled_copy_path_cache = cached
        return cached

    def _is_on_compiled_copy(self, violation: RuleViolation) -> bool:
        """Whether *violation* sits on an APM-compiled copy (block or path)."""
        if violation.block is not None and _node_content_suppressed(violation.block):
            return True
        path = violation.file_path
        if path is None:
            return False
        # ``safe_resolve`` matches how ``LintTarget.resolved_path`` normalizes
        # the node paths in the set, and never raises on a symlink loop or an
        # unreadable parent the way ``Path.resolve()`` would.
        resolved = safe_resolve(path) or path
        return resolved in self._compiled_copy_paths()

    def _is_vendor_managed(self, file_path: Optional[Path]) -> bool:
        """Whether *file_path* belongs to a plugin installed into this checkout.

        Content under ``.codex/plugins/`` is run by this repository but was
        not written by it. The Codex-specific rules already stand down on
        it, and so do the Agent Skill fixers — but a skill installed there
        is an ordinary ``SkillBlock``, so every generic ``content-*`` fix
        would otherwise apply to it and rewrite a vendor-managed file the
        developer cannot own. Drawing the line here covers every rule,
        including ones added later that never think about Codex.
        """
        if file_path is None:
            return False
        cached = self._vendor_managed_cache.get(file_path)
        if cached is None:
            cached = self.context.is_codex_installed_plugin(file_path)
            self._vendor_managed_cache[file_path] = cached
        return cached

    def _filter_violations(
        self, violations: List[RuleViolation], record_baseline: bool = True
    ) -> List[RuleViolation]:
        """Filter violations by global excludes, per-rule excludes, and inline suppression.

        When *record_baseline* is False, baseline subtraction still applies
        but stale/suppressed accounting is left untouched — used for the
        per-rule calls in :meth:`fix`, which would otherwise overwrite the
        accounting with only the last rule's view of the baseline.
        """
        kept: List[RuleViolation] = []
        for v in violations:
            if self._is_excluded(v):
                logger.info(
                    "Suppressed %-30s %s (global exclude)",
                    v.rule_id,
                    v.file_path or "(no file)",
                )
            elif self._is_rule_excluded(v.rule_id, v.file_path):
                logger.info(
                    "Suppressed %-30s %s (per-rule exclude)",
                    v.rule_id,
                    v.file_path or "(no file)",
                )
            elif self._is_inline_suppressed(v):
                logger.info(
                    "Suppressed %-30s %s:%s (inline directive)",
                    v.rule_id,
                    v.file_path or "(no file)",
                    v.file_line or "?",
                )
            elif _is_prose_duplicate_rule(v.rule_id) and self._is_on_compiled_copy(v):
                # A compiled copy of a source read elsewhere: its prose-quality
                # and budget findings would double the source's, so drop them.
                # Structural-validity findings (a malformed compiled .mdc, a
                # broken post-compile import) and every security finding still
                # fire — they are unique to the artifact that ships, so a
                # hand-edited copy cannot hide a defect or a payload from them.
                logger.info(
                    "Suppressed %-30s %s (APM-compiled copy, prose duplicate)",
                    v.rule_id,
                    v.file_path or "(no file)",
                )
            elif self._is_vendor_managed(v.file_path) or (
                v.block is not None and v.block.diagnostic_only
            ):
                # Still reported — a hostile third-party skill is worth
                # knowing about — but never advertised as fixable, because
                # fix() is about to stand down on it. Confidence goes with
                # fixability, or JSON/SARIF would still claim SAFE/SUGGEST.
                # Same reasoning for a diagnostic-only block: its body is
                # extracted from a document of another format, so a fix
                # computed against it has no span to splice back into.
                v.fixable = False
                v.fix_confidence = None
                kept.append(v)
            else:
                kept.append(v)
        if len(kept) < len(violations):
            logger.info(
                "Filtered %d of %d violations via excludes/suppression",
                len(violations) - len(kept),
                len(violations),
            )

        if self._baseline is not None:
            from .baseline import filter_baselined_violations

            before = len(kept)
            baseline_root = self._baseline.root_path or self.context.root_path
            kept, stale = filter_baselined_violations(kept, self._baseline, baseline_root)
            if record_baseline:
                self._stale_baseline_entries = stale
                self._baseline_suppressed_count = before - len(kept)
            if before > len(kept):
                logger.info(
                    "Filtered %d of %d violations via baseline",
                    before - len(kept),
                    before,
                )
            if stale:
                logger.info(
                    "Baseline: %d stale entries (violations no longer present)",
                    len(stale),
                )

        return kept

    @property
    def stale_baseline_entries(self) -> List["BaselineEntry"]:
        return self._stale_baseline_entries

    @property
    def baseline_suppressed_count(self) -> int:
        return self._baseline_suppressed_count

    def run(
        self, progress: Optional[Callable[[int, int, str], None]] = None
    ) -> List[RuleViolation]:
        """
        Run all enabled rules

        Args:
            progress: Optional callback invoked before each rule check with
                ``(rule_number, total_rules, rule_id)`` — used by the CLI to
                show interactive progress on long lints.

        Returns:
            List of all violations found
        """
        violations = self._validate_config()

        logger.info("Running %d enabled rules", len(self.rules))
        total = len(self.rules)
        for index, rule in enumerate(self.rules, 1):
            if progress is not None:
                progress(index, total, rule.rule_id)
            try:
                rule_violations = rule.check(self.context)
                if rule_violations:
                    logger.info(
                        "Rule %-30s found %d violation(s)", rule.rule_id, len(rule_violations)
                    )
                violations.extend(rule_violations)
            except Exception as e:
                print(f"Error running rule {rule.rule_id}: {e}", file=sys.stderr)
                violations.append(self._crash_violation(rule, e))

        # Tree contributors run lazily inside build_lint_tree (triggered by
        # the rule checks above), so their failures are only known now.
        _ = self.context.lint_tree
        violations.extend(self._lint_tree_error_violations())
        violations.extend(self._plugin_extension_error_violations())

        return self._filter_violations(violations)

    @staticmethod
    def _crash_violation(rule: Rule, exc: Exception, action: str = "check") -> RuleViolation:
        """Surface a rule crash as an ERROR violation so it affects the exit code."""
        return RuleViolation(
            rule_id="rule-execution-error",
            severity=Severity.ERROR,
            message=(
                f"Rule '{rule.rule_id}' crashed during {action}:"
                f" {exc.__class__.__name__}: {exc}"
            ),
        )

    def fix(
        self, progress: Optional[Callable[[int, int, str], None]] = None
    ) -> tuple[List[RuleViolation], List[AutofixResult]]:
        """
        Run all enabled rules and attempt to fix violations.

        Args:
            progress: Optional callback invoked before each rule check with
                ``(rule_number, total_rules, rule_id)``.

        Returns:
            Tuple of (remaining violations, autofix results)
        """
        # Config warnings go through the same filter pipeline run() uses
        # (inline suppression, excludes, baseline) — but `checked` keeps the
        # raw list so the final accounting pass sees everything, exactly
        # like the raw per-rule extends below.
        config_violations = self._validate_config()
        all_violations = self._filter_violations(config_violations, record_baseline=False)
        all_fixes: List[AutofixResult] = []
        checked: List[RuleViolation] = list(config_violations)

        total = len(self.rules)
        for index, rule in enumerate(self.rules, 1):
            if progress is not None:
                progress(index, total, rule.rule_id)
            try:
                rule_violations = rule.check(self.context)
            except Exception as e:
                print(f"Error running rule {rule.rule_id}: {e}", file=sys.stderr)
                all_violations.append(self._crash_violation(rule, e))
                continue

            checked.extend(rule_violations)
            visible = self._filter_violations(rule_violations, record_baseline=False)

            # Diagnostic-only blocks never reach a fixer at all. Clearing
            # their fixability metadata is presentation; a third-party rule's
            # ``fix()`` does not read it, so handing the violation over would
            # still invite a rewrite of text that has no honest span in the
            # file that holds it (a prompt decoded out of JSON, say).
            fixable_input = [v for v in visible if v.block is None or not v.block.diagnostic_only]
            if fixable_input and rule.supports_autofix:
                try:
                    fixes = [
                        f
                        for f in rule.fix(self.context, fixable_input)
                        if not self._is_vendor_managed(f.file_path)
                    ]
                    all_fixes.extend(fixes)
                    fixed_violations = {id(v) for fix in fixes for v in fix.violations_fixed}
                    remaining = [v for v in visible if id(v) not in fixed_violations]
                    all_violations.extend(remaining)
                except Exception as e:
                    print(f"Error fixing rule {rule.rule_id}: {e}", file=sys.stderr)
                    all_violations.append(self._crash_violation(rule, e, action="fix"))
                    all_violations.extend(visible)
            else:
                all_violations.extend(visible)

        _ = self.context.lint_tree
        all_violations.extend(self._lint_tree_error_violations())
        all_violations.extend(self._plugin_extension_error_violations())

        # Baseline stale/suppressed accounting must consider all rules'
        # violations together, exactly as run() does — the per-rule calls
        # above skip it (record_baseline=False).
        if self._baseline is not None:
            self._filter_violations(checked)

        return all_violations, all_fixes

    @staticmethod
    def _first_per_file(
        fixes: List[AutofixResult],
    ) -> tuple[List[AutofixResult], bool]:
        """Snapshot-isolation filter: first-committer-wins per file.

        Returns the independent subset (at most one fix per file) and
        whether any fixes were deferred due to file-level conflicts.
        Deferred fixes are not applied — the next pass will re-derive
        them against the committed file state.
        """
        seen: set[Path] = set()
        independent: List[AutofixResult] = []
        has_conflicts = False
        for fix in fixes:
            targets = {safe_resolve(fix.file_path) or fix.file_path}
            if fix.rename_from is not None:
                targets.add((safe_resolve(fix.rename_from) or fix.rename_from))
            if any(t in seen for t in targets):
                has_conflicts = True
            else:
                seen.update(targets)
                independent.append(fix)
        return independent, has_conflicts

    def fix_and_apply(
        self,
        confidence: AutofixConfidence = AutofixConfidence.SAFE,
        max_passes: int = 10,
        dry_run: bool = False,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> tuple[List[AutofixResult], List[AutofixResult]]:
        """Fixed-point iteration over autofix passes with snapshot isolation.

        Each fix is a pre-computed transformation against a file snapshot.
        When two fixes target the same file, the second holds a stale
        snapshot — a classic write-write conflict.

        This method resolves conflicts via first-committer-wins: each pass
        applies at most one fix per file (the independent set of the
        conflict graph).  Conflicting fixes are never applied with stale
        data — they are discarded and re-derived on the next pass against
        the committed file state.

        Converges when a pass produces no file-level conflicts, or when
        no new fixes are found (the fixed point).

        Args:
            confidence: Minimum confidence level to apply.
            max_passes: Safety cap on iterations.

        Returns:
            Tuple of (applied fixes, suggested-but-not-applied fixes).
        """
        from .rules.builtin.utils import invalidate_read_caches

        all_applied: List[AutofixResult] = []
        all_suggested: List[AutofixResult] = []

        allowed = {AutofixConfidence.SAFE}
        if confidence == AutofixConfidence.SUGGEST:
            allowed.add(AutofixConfidence.SUGGEST)

        for _ in range(max_passes):
            _violations, fixes = self.fix(progress=progress)
            if not fixes:
                break

            applicable = [f for f in fixes if f.confidence in allowed]
            suggested = [f for f in fixes if f.confidence not in allowed]
            all_suggested.extend(suggested)

            if not applicable:
                break

            independent, has_conflicts = self._first_per_file(applicable)

            if dry_run:
                all_applied.extend(independent)
                break

            applied = self.apply_fixes(
                independent,
                confidence,
                root_path=self.context.root_path,
            )
            all_applied.extend(applied)

            # An on_apply side effect (e.g. recording a rename in the
            # manifest) can unlock new violations for other rules, so a
            # further pass is needed even without file-level conflicts.
            state_changed = any(f.on_apply is not None for f in applied)
            if not applied or not (has_conflicts or state_changed):
                break

            invalidate_read_caches()
            self.context.rebuild_lint_tree()
            if hasattr(self, "_suppression_cache"):
                self._suppression_cache.clear()

        return all_applied, all_suggested

    @staticmethod
    def apply_fixes(
        fixes: List[AutofixResult],
        confidence: AutofixConfidence = AutofixConfidence.SAFE,
        root_path: Optional[Path] = None,
    ) -> List[AutofixResult]:
        """
        Write fix results to disk.

        Args:
            fixes: Autofix results to apply
            confidence: Minimum confidence level to apply
                        (SAFE = only safe,
                         SUGGEST = safe + suggest)
            root_path: Trusted repository boundary for atomic writes

        Returns:
            List of fixes that were actually applied
        """
        applied: List[AutofixResult] = []
        allowed = {AutofixConfidence.SAFE}
        if confidence == AutofixConfidence.SUGGEST:
            allowed.add(AutofixConfidence.SUGGEST)

        for fix in fixes:
            if fix.confidence not in allowed:
                continue

            # A target may be swapped for a symlink after discovery or
            # between fixed-point passes. Re-check at the write boundary so
            # autofix never follows it outside the repository.
            if safe_is_symlink(fix.file_path) or (
                fix.rename_from is not None and safe_is_symlink(fix.rename_from)
            ):
                logger.warning("Skipping autofix for symlinked path: %s", fix.file_path)
                continue

            try:
                if fix.rename_from is not None:
                    # Rename operation: use Path.rename() for atomicity and
                    # safety on case-insensitive filesystems (macOS/Windows).
                    # If the source no longer exists or the target already exists
                    # (and isn't the same file on a case-insensitive FS), skip.
                    src = fix.rename_from
                    dst = fix.file_path
                    if not src.exists():
                        continue
                    if root_path is None:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                    else:
                        mkdir_parents_anchored(dst.parent, root=root_path)
                    # On case-insensitive filesystems src and dst may resolve to
                    # the same inode even when their names differ in casing.
                    # Path.rename() handles this correctly, but we must not skip
                    # a case-only rename via the ``dst.exists()`` guard.
                    same_file = (safe_resolve(src) or src) == (safe_resolve(dst) or dst)
                    if dst.exists() and not same_file:
                        continue
                    if root_path is None:
                        src.rename(dst)
                    else:
                        rename_path_anchored(src, dst, root=root_path)
                    # If the content also changed, write the updated content.
                    # write_text_preserving restores the file's original BOM
                    # and CRLF/LF line endings (see utils) so an autofix only
                    # changes the span it targeted, not the whole file.
                    if fix.fixed_content != fix.original_content:
                        write_text_preserving(dst, fix.fixed_content, root=root_path)
                else:
                    write_text_preserving(
                        fix.file_path,
                        fix.fixed_content,
                        root=root_path,
                    )
            except OSError as exc:
                logger.warning(
                    "Failed to apply fix for %s on %s: %s",
                    fix.rule_id,
                    fix.file_path,
                    exc,
                )
                continue

            if fix.on_apply is not None:
                try:
                    fix.on_apply()
                except OSError as exc:
                    logger.warning(
                        "on_apply side effect failed for %s on %s: %s",
                        fix.rule_id,
                        fix.file_path,
                        exc,
                    )

            applied.append(fix)

        return applied
