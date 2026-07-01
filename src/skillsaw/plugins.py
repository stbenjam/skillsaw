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

import inspect
import logging
import types
from dataclasses import dataclass, field
from importlib import metadata
from typing import Iterable, List, Optional, Set, Type

from .rule import Rule

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "skillsaw.plugins"

# Module attribute a plugin can set to declare its rules explicitly.
RULES_ATTRIBUTE = "SKILLSAW_RULES"


@dataclass
class PluginInfo:
    """A discovered plugin and the rule classes it provides."""

    name: str
    """Entry point name (the plugin's short name, e.g. ``acme-rules``)."""

    source: str
    """Entry point value (``module`` or ``module:attr``)."""

    distribution: Optional[str] = None
    """PyPI distribution name providing the plugin, when known."""

    version: Optional[str] = None
    """Distribution version, when known."""

    rule_classes: List[Type[Rule]] = field(default_factory=list)

    error: Optional[str] = None
    """Load failure message; when set, ``rule_classes`` is empty."""


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
        declared = getattr(obj, RULES_ATTRIBUTE, None)
        if declared is not None:
            return _rules_from_sequence(declared, f"{source}:{RULES_ATTRIBUTE}")
        # No explicit declaration: collect every concrete Rule subclass in
        # the module namespace (mirrors the local custom-rule file loader).
        seen: Set[type] = set()
        found = []
        for name in dir(obj):
            attr = getattr(obj, name)
            if _is_concrete_rule(attr) and attr not in seen:
                seen.add(attr)
                found.append(attr)
        return found
    if _is_concrete_rule(obj):
        return [obj]  # type: ignore[list-item]
    if isinstance(obj, (list, tuple)):
        return _rules_from_sequence(obj, source)
    if callable(obj):
        return _rules_from_sequence(obj(), source)
    raise TypeError(
        f"entry point '{source}' must reference a module, a Rule class, "
        f"a list of Rule classes, or a callable returning Rule classes — "
        f"got {type(obj).__name__}"
    )


def _entry_point_dist(ep) -> tuple:
    """(distribution name, version) for an entry point, best effort.

    ``EntryPoint.dist`` only exists on Python 3.10+; fake entry points in
    tests may lack it too.
    """
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None, None
    try:
        return dist.name, dist.version
    except Exception:  # pragma: no cover - metadata access can fail oddly
        return None, None


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
        except Exception as e:
            info.error = f"{e.__class__.__name__}: {e}"
            logger.warning("Plugin %-30s failed to load: %s", ep.name, info.error)
        else:
            logger.info("Plugin %-30s loaded (%d rule(s))", ep.name, len(info.rule_classes))
        plugins.append(info)
    return plugins
