"""
Rule plugin discovery and loading.

skillsaw plugins are ordinary Python packages that publish additional
:class:`~skillsaw.rule.Rule` classes through the ``skillsaw.plugins``
entry point group.  Installing such a package (``pip install
skillsaw-acme-rules``) is all it takes — the rules are discovered
automatically on the next lint run.

An entry point may reference any of:

- a **module** — its ``SKILLSAW_RULES`` list is used when present,
  otherwise every concrete :class:`Rule` subclass in the module's
  namespace is collected;
- a **list/tuple** of Rule classes (``pkg.rules:RULES``);
- a **Rule class** (``pkg.rules:MyRule``);
- a **callable** returning an iterable of Rule classes
  (``pkg.rules:get_rules``).

Loading is fault-isolated: a broken plugin never aborts the lint.  The
failure is captured on its :class:`PluginInfo` and the linter surfaces
it as a ``plugin-load-error`` violation instead.
"""

from __future__ import annotations

import functools
import importlib
import inspect
import logging
import re
import types
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Iterable, List, Optional, Set, Type

from .rule import Rule

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "skillsaw.plugins"

# Module attribute a plugin can set to declare its rules explicitly.
RULES_ATTRIBUTE = "SKILLSAW_RULES"

# Module attribute declaring custom repository types (list of PluginRepoType).
REPO_TYPES_ATTRIBUTE = "SKILLSAW_REPO_TYPES"

# Module attribute declaring lint tree contributors: callables invoked as
# ``contribute(context, root)`` during tree construction, returning an
# iterable of block/node instances to attach at the root (or None).
TREE_CONTRIBUTORS_ATTRIBUTE = "SKILLSAW_TREE_CONTRIBUTORS"

_REPO_TYPE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class PluginRepoType:
    """A repository type contributed by a plugin.

    When ``detect`` returns True for the linted repository, the type's
    ``name`` behaves like a builtin repository type: rules (plugin, custom,
    or builtin) can list it in ``repo_types`` to scope ``enabled: auto``
    activation, and it appears in the lint report's detected types.
    """

    name: str
    """Kebab-case type name (e.g. ``acme``). Must not collide with builtin
    repository type values or other plugins' types."""

    detect: Callable[[Path], bool]
    """Called with the repository root path; True when the repo is this type."""

    description: str = ""

    content_paths: List[str] = field(default_factory=list)
    """Glob patterns (relative to the repo root) pulled into content linting
    when the type is detected — the plugin-declared equivalent of the
    ``content-paths`` config key. Matched markdown/text files become content
    blocks and get every ``content-*`` rule automatically."""

    def validate(self) -> None:
        if not isinstance(self.name, str) or not _REPO_TYPE_NAME_RE.match(self.name):
            raise TypeError(f"PluginRepoType name must be a kebab-case string, got {self.name!r}")
        if not callable(self.detect):
            raise TypeError(f"PluginRepoType '{self.name}': detect must be callable")
        if not isinstance(self.content_paths, (list, tuple)) or not all(
            isinstance(p, str) for p in self.content_paths
        ):
            raise TypeError(
                f"PluginRepoType '{self.name}': content_paths must be a list of glob strings"
            )
        for pattern in self.content_paths:
            # Path.glob() raises NotImplementedError on absolute patterns;
            # reject them at load time (both POSIX and Windows forms) so the
            # plugin fails with one clear error instead of crashing every rule.
            if PurePosixPath(pattern).is_absolute() or PureWindowsPath(pattern).is_absolute():
                raise ValueError(
                    f"PluginRepoType '{self.name}': content_paths pattern "
                    f"{pattern!r} is absolute — glob patterns must be "
                    "relative to the repository root"
                )


@dataclass
class PluginInfo:
    """A discovered plugin and the rules/extensions it provides."""

    name: str
    """Entry point name (the plugin's short name, e.g. ``acme-rules``)."""

    source: str
    """Entry point value (``module`` or ``module:attr``)."""

    distribution: Optional[str] = None
    """PyPI distribution name providing the plugin, when known."""

    version: Optional[str] = None
    """Distribution version, when known."""

    rule_classes: List[Type[Rule]] = field(default_factory=list)

    repo_types: List[PluginRepoType] = field(default_factory=list)
    """Custom repository types declared via ``SKILLSAW_REPO_TYPES``."""

    tree_contributors: List[Callable] = field(default_factory=list)
    """Lint tree contributors declared via ``SKILLSAW_TREE_CONTRIBUTORS``."""

    error: Optional[str] = None
    """Load failure message; when set, the other collections are empty."""


def _iter_entry_points():
    """Yield entry points in the plugin group.

    Isolated as a seam so tests can substitute fake entry points, and to
    paper over the ``entry_points()`` API difference: the ``group``
    keyword exists only on Python 3.10+, while 3.9 returns a dict.
    """
    try:
        return list(metadata.entry_points(group=ENTRY_POINT_GROUP))
    except TypeError:  # Python 3.9: entry_points() takes no kwargs
        return list(metadata.entry_points().get(ENTRY_POINT_GROUP, []))


def installed_plugin_names() -> List[str]:
    """Names of installed plugins, without importing any plugin code.

    Entry point *listing* only reads package metadata — safe to call even
    when plugin loading is disabled.
    """
    names = []
    for ep in _iter_entry_points():
        if ep.name not in names:
            names.append(ep.name)
    return names


def _is_concrete_rule(obj: object) -> bool:
    return (
        isinstance(obj, type)
        and issubclass(obj, Rule)
        and obj is not Rule
        and not inspect.isabstract(obj)
    )


def _rules_from_sequence(seq: Iterable, source: str) -> List[Type[Rule]]:
    rules = []
    for item in seq:
        if not _is_concrete_rule(item):
            raise TypeError(
                f"{source} yielded {item!r}, which is not a concrete " "skillsaw.Rule subclass"
            )
        rules.append(item)
    return rules


def _resolve_rule_classes(obj: object, source: str) -> List[Type[Rule]]:
    """Extract rule classes from whatever the entry point resolved to."""
    if isinstance(obj, types.ModuleType):
        try:
            declared = getattr(obj, RULES_ATTRIBUTE, None)
        except Exception:
            # A module-level __getattr__ (PEP 562) raising something other
            # than AttributeError escapes getattr's default handling.
            declared = None
        if declared is not None:
            return _rules_from_sequence(declared, f"{source}:{RULES_ATTRIBUTE}")
        # No explicit declaration: collect every concrete Rule subclass in
        # the module namespace (mirrors the local custom-rule file loader).
        seen: Set[type] = set()
        found = []
        for name in dir(obj):
            try:
                attr = getattr(obj, name)
            except Exception:
                # A module-level __getattr__ (PEP 562) may raise for names
                # dir() reported; skip those rather than failing the plugin.
                continue
            if _is_concrete_rule(attr) and attr not in seen:
                seen.add(attr)
                found.append(attr)
        return found
    if isinstance(obj, type):
        # Classes are callable; reject non-rule/abstract classes here so
        # they don't fall into the callable branch and get instantiated.
        if _is_concrete_rule(obj):
            return [obj]
        raise TypeError(
            f"entry point '{source}' references class {obj.__name__}, "
            "which is not a concrete skillsaw.Rule subclass"
        )
    if isinstance(obj, (list, tuple)):
        return _rules_from_sequence(obj, source)
    if callable(obj):
        return _rules_from_sequence(obj(), source)
    raise TypeError(
        f"entry point '{source}' must reference a module, a Rule class, "
        f"a list of Rule classes, or a callable returning Rule classes — "
        f"got {type(obj).__name__}"
    )


@functools.lru_cache(maxsize=1)
def _dist_by_entry_point():
    """Map (entry point name, value) -> Distribution, for Python 3.9.

    On 3.9 ``EntryPoint`` objects carry no ``dist`` back-reference, so the
    owning distribution must be recovered by scanning installed
    distributions' declared entry points. Built lazily and cached — it is
    only consulted when ``ep.dist`` is unavailable.
    """
    mapping = {}
    for dist in metadata.distributions():
        try:
            for ep in dist.entry_points:
                if ep.group == ENTRY_POINT_GROUP:
                    mapping[(ep.name, ep.value)] = dist
        except Exception:  # pragma: no cover - malformed dist metadata
            continue
    return mapping


def _module_attr(module_name: str, attribute: str):
    """Read a declaration attribute from a plugin's module, tolerating
    raising PEP 562 ``__getattr__`` implementations."""
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute, None)
    except Exception:
        return None


def _resolve_repo_types(module_name: str) -> List[PluginRepoType]:
    declared = _module_attr(module_name, REPO_TYPES_ATTRIBUTE)
    if declared is None:
        return []
    if not isinstance(declared, (list, tuple)):
        raise TypeError(f"{REPO_TYPES_ATTRIBUTE} must be a list of PluginRepoType")
    repo_types = []
    for item in declared:
        if not isinstance(item, PluginRepoType):
            raise TypeError(f"{REPO_TYPES_ATTRIBUTE} entries must be PluginRepoType, got {item!r}")
        item.validate()
        repo_types.append(item)
    return repo_types


def _resolve_tree_contributors(module_name: str) -> List[Callable]:
    declared = _module_attr(module_name, TREE_CONTRIBUTORS_ATTRIBUTE)
    if declared is None:
        return []
    if not isinstance(declared, (list, tuple)) or not all(callable(c) for c in declared):
        raise TypeError(f"{TREE_CONTRIBUTORS_ATTRIBUTE} must be a list of callables")
    return list(declared)


def _entry_point_dist(ep) -> tuple:
    """(distribution name, version) for an entry point, best effort.

    ``EntryPoint.dist`` only exists on Python 3.10+; fake entry points in
    tests may lack it too.
    """
    dist = getattr(ep, "dist", None)
    if dist is None:
        dist = _dist_by_entry_point().get((ep.name, ep.value))
    if dist is None:
        return None, None
    try:
        # Distribution.name is also 3.10+; fall back to the metadata field.
        name = getattr(dist, "name", None) or dist.metadata["Name"]
        return name, dist.version
    except Exception:  # pragma: no cover - metadata access can fail oddly
        return None, None


@dataclass
class ExtensionProblem:
    """A non-fatal problem found while registering plugin extensions."""

    severity: str  # "error" or "warning"
    message: str


def register_extensions(context, plugins: List[PluginInfo]) -> List[ExtensionProblem]:
    """Register plugin repo types and tree contributors on a context.

    Runs each declared repo type's detector (fault-isolated), records
    detected type names in ``context.plugin_repo_types``, collects detected
    types' ``content_paths`` into ``context.plugin_content_paths``, and hands
    tree contributors to the context for ``build_lint_tree``.

    Idempotent per context: repeated calls (e.g. two Linters sharing one
    context) are no-ops, so contributors never accumulate duplicates and
    problems are reported once.

    Returns problems (name collisions, crashed detectors) for the caller to
    surface; the linter maps them to violations, the CLI prints them.
    """
    from .context import RepositoryType

    if getattr(context, "_plugin_extensions_registered", False):
        return []
    context._plugin_extensions_registered = True

    problems: List[ExtensionProblem] = []
    builtin_type_values = {t.value for t in RepositoryType}
    registered_types: dict = {}  # type name -> plugin name
    contributed_paths: List[str] = []

    for plugin in plugins:
        if plugin.error:
            continue
        for repo_type in plugin.repo_types:
            if repo_type.name in builtin_type_values:
                problems.append(
                    ExtensionProblem(
                        "warning",
                        f"Plugin '{plugin.name}' declares repo type "
                        f"'{repo_type.name}', which is a builtin repository "
                        "type — the declaration was skipped.",
                    )
                )
                continue
            if repo_type.name in registered_types:
                problems.append(
                    ExtensionProblem(
                        "warning",
                        f"Plugin '{plugin.name}' declares repo type "
                        f"'{repo_type.name}', already provided by plugin "
                        f"'{registered_types[repo_type.name]}' — the "
                        "declaration was skipped.",
                    )
                )
                continue
            registered_types[repo_type.name] = plugin.name

            try:
                detected = bool(repo_type.detect(context.root_path))
            except Exception as e:
                problems.append(
                    ExtensionProblem(
                        "error",
                        f"Plugin '{plugin.name}': repo type '{repo_type.name}' "
                        f"detector crashed: {e.__class__.__name__}: {e}",
                    )
                )
                continue
            if detected:
                context.plugin_repo_types.add(repo_type.name)
                contributed_paths.extend(repo_type.content_paths)
                logger.info("Repo type %-24s detected (plugin: %s)", repo_type.name, plugin.name)

        context.plugin_tree_contributors.extend(
            (plugin.name, contributor) for contributor in plugin.tree_contributors
        )

    if contributed_paths:
        # Separate from context.content_paths (user config): the Linter
        # resets that attribute on construction, and plugin contributions
        # must survive a shared context being reused.
        context.plugin_content_paths.extend(
            p for p in contributed_paths if p not in context.plugin_content_paths
        )
    if contributed_paths or context.plugin_tree_contributors:
        # The tree is built lazily on first access, so nothing is wasted;
        # dropping any cached tree guarantees the contributions apply.
        context.rebuild_lint_tree()
    return problems


def load_plugins(disabled: Optional[Set[str]] = None) -> List[PluginInfo]:
    """Discover and load all installed skillsaw plugins.

    Args:
        disabled: Plugin (entry point) names to skip without importing.

    Returns:
        One :class:`PluginInfo` per entry point, in discovery order.
        Plugins that fail to load are returned with ``error`` set rather
        than raising, so one broken plugin cannot take down the lint.
        Disabled plugins are omitted entirely.
    """
    disabled = disabled or set()
    plugins: List[PluginInfo] = []
    for ep in _iter_entry_points():
        if ep.name in disabled:
            logger.info("Plugin %-30s disabled in config", ep.name)
            continue
        dist_name, dist_version = _entry_point_dist(ep)
        info = PluginInfo(
            name=ep.name,
            source=ep.value,
            distribution=dist_name,
            version=dist_version,
        )
        try:
            obj = ep.load()
            info.rule_classes = _resolve_rule_classes(obj, ep.value)
            # Extension declarations live as sibling attributes on the entry
            # point's module (already imported by ep.load()), so they work
            # for every entry point form, not just the module form.
            module_name = ep.value.split(":", 1)[0]
            info.repo_types = _resolve_repo_types(module_name)
            info.tree_contributors = _resolve_tree_contributors(module_name)
        except Exception as e:
            info.error = f"{e.__class__.__name__}: {e}"
            info.rule_classes = []
            info.repo_types = []
            info.tree_contributors = []
            logger.warning("Plugin %-30s failed to load: %s", ep.name, info.error)
        else:
            logger.info(
                "Plugin %-30s loaded (%d rule(s), %d repo type(s), %d tree contributor(s))",
                ep.name,
                len(info.rule_classes),
                len(info.repo_types),
                len(info.tree_contributors),
            )
        plugins.append(info)
    return plugins
