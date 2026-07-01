"""
Builtin linting rules for Claude Code plugins

Rules are discovered automatically: every concrete ``Rule`` subclass defined
in a module under this package is registered in ``BUILTIN_RULES``. Adding a
new rule only requires writing the class — there is no import block, list,
or config dict to update. Rule defaults (enabled mode, severity) live on the
class itself (``Rule.default_enabled`` / ``Rule.default_severity``) and
``LinterConfig.default()`` is generated from this registry.
"""

import importlib
import inspect
import pkgutil

from ...rule import Rule


def _reraise(_name):
    # pkgutil.walk_packages swallows ImportErrors from subpackages unless an
    # onerror hook is given — a broken rule package must fail loudly, not
    # silently drop its rules from the registry.
    raise


def _discover_rule_classes():
    """Import every module in this package and collect Rule subclasses."""
    classes = []
    seen = set()
    prefix = __name__ + "."
    for modinfo in pkgutil.walk_packages(__path__, prefix, onerror=_reraise):
        module = importlib.import_module(modinfo.name)
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, Rule)
                and not inspect.isabstract(obj)
                and obj.__module__.startswith(prefix)
                and obj not in seen
            ):
                seen.add(obj)
                classes.append(obj)
    return classes


def _build_registry():
    """Map rule_id -> rule class, sorted by rule_id, rejecting duplicates."""
    by_id = {}
    for cls in _discover_rule_classes():
        rule_id = cls().rule_id
        existing = by_id.get(rule_id)
        if existing is not None and existing is not cls:
            raise RuntimeError(
                f"Duplicate rule_id {rule_id!r}: "
                f"{existing.__module__}.{existing.__qualname__} and "
                f"{cls.__module__}.{cls.__qualname__}"
            )
        by_id[rule_id] = cls
    return dict(sorted(by_id.items()))


#: rule_id -> rule class for every builtin rule, sorted by rule_id.
BUILTIN_RULE_REGISTRY = _build_registry()

#: All builtin rule classes, sorted by rule_id.
BUILTIN_RULES = list(BUILTIN_RULE_REGISTRY.values())


def __getattr__(name):
    # Keep ``from skillsaw.rules.builtin import SkillFrontmatterRule`` working
    # without a hand-maintained re-export block (PEP 562).
    for cls in BUILTIN_RULES:
        if cls.__name__ == name:
            return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Computed on purpose — the registry is the source of truth, so the export
# list can't drift from it. Ruff's PLE0604 only accepts string literals.
__all__ = [  # noqa: PLE0604
    "BUILTIN_RULES",
    "BUILTIN_RULE_REGISTRY",
    *sorted(cls.__name__ for cls in BUILTIN_RULES),
]
