"""
Configuration management for skillsaw
"""

import copy
import functools
import os
import re

import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from .context import RepositoryContext

_DEFAULT_VERSION = "0.6.0"

_DEFAULT_EXCLUDE_PATTERNS = [
    "**/template/**",
    "**/templates/**",
    "**/_template/**",
]


def _parse_version(v: str) -> Tuple[int, ...]:
    """Parse a version string leniently into a comparable numeric tuple.

    The ``version`` field is user-controlled config, so common variants of
    ``X.Y.Z`` must not crash the lint: a leading ``v`` (``v0.12.0``) and
    pre-release/build suffixes (``0.12.0-rc1``, ``0.12.0+build5``) are
    accepted. Components that still aren't numeric contribute their leading
    digits, or 0 when there are none. Results are zero-padded to at least
    three components so short versions like "1.2" compare correctly against
    "1.2.0" (tuple comparison would otherwise rank (1, 2) below (1, 2, 0)).
    """
    v = str(v).strip().lstrip("vV")
    v = re.split(r"[-+]", v, maxsplit=1)[0]
    parts = []
    for component in v.split("."):
        m = re.match(r"\d+", component.strip())
        parts.append(int(m.group()) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


@dataclass
class LinterConfig:
    """Configuration for the linter"""

    version: str = ""
    rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    custom_rules: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    content_paths: List[str] = field(default_factory=list)
    strict: bool = False
    # Rule plugins (pip-installed packages exposing skillsaw.plugins entry
    # points). ``plugins_enabled: False`` skips all of them; ``disabled_plugins``
    # skips specific plugins by entry point name.
    plugins_enabled: bool = True
    disabled_plugins: List[str] = field(default_factory=list)
    config_dir: Optional[Path] = None
    # Non-fatal problems found while loading (missing version, unknown keys).
    # Excluded from equality so two configs loaded the same way still compare
    # equal regardless of the advisory messages attached.
    warnings: List[str] = field(default_factory=list, compare=False)

    # Recognised top-level config keys; anything else triggers a load warning.
    _KNOWN_KEYS = frozenset(
        {
            "version",
            "rules",
            "custom-rules",
            "exclude",
            "content-paths",
            "strict",
            "plugins",
        }
    )

    @classmethod
    def from_file(cls, config_path: Path) -> "LinterConfig":
        """
        Load configuration from a config file

        Args:
            config_path: Path to configuration file

        Returns:
            LinterConfig instance
        """
        if not config_path.exists():
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (yaml.YAMLError, IOError, UnicodeDecodeError) as e:
            raise ValueError(f"Failed to load config from {config_path}: {e}") from e

        # Only an empty document (None) is an empty config; falsy non-mappings
        # ([], false, 0, "") are malformed and must reach the type check below
        # rather than being coerced to {} by ``or {}``.
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError(
                f"config root must be a mapping, got {type(data).__name__}. "
                "Expected top-level keys like 'rules:', 'exclude:', 'version:'."
            )

        load_warnings: List[str] = []
        unknown_keys = set(data) - cls._KNOWN_KEYS
        if unknown_keys:
            load_warnings.append(
                "unknown config key(s) ignored: "
                + ", ".join(sorted(map(str, unknown_keys)))
                + ". Known keys: "
                + ", ".join(sorted(cls._KNOWN_KEYS))
            )
        raw_version = data.get("version")
        if raw_version is None:
            # Covers both a missing key and an explicit ``version:`` (None) —
            # both would otherwise version-gate as 0.0.0 and disable newer rules.
            load_warnings.append(
                f"config has no 'version' field; defaulting to {_DEFAULT_VERSION}, so rules "
                "added in later versions are silently disabled. Set 'version' to your "
                "skillsaw version to enable them."
            )

        raw_rules = data.get("rules")
        raw_custom_rules = data.get("custom-rules")
        raw_exclude = data.get("exclude")
        raw_strict = data.get("strict")

        if raw_rules is None:
            rules = {}
        elif isinstance(raw_rules, dict):
            rules = raw_rules
        else:
            raise ValueError(
                f"'rules' must be a mapping, got {type(raw_rules).__name__}. "
                "Each rule should be a key with a mapping value, e.g.:\n"
                "  rules:\n"
                "    plugin-json-required:\n"
                "      enabled: true"
            )

        for rule_id, rule_config in rules.items():
            if rule_config is None:
                rules[rule_id] = {}
            elif not isinstance(rule_config, dict):
                raise ValueError(
                    f"'rules.{rule_id}' must be a mapping or null, "
                    f"got {type(rule_config).__name__}"
                )
            else:
                if "enabled" in rule_config:
                    enabled = rule_config["enabled"]
                    if enabled is not True and enabled is not False and enabled != "auto":
                        raise ValueError(
                            f"'rules.{rule_id}.enabled' must be true, false, "
                            f'or "auto", got {enabled!r}'
                        )

        if raw_custom_rules is None:
            custom_rules = []
        elif isinstance(raw_custom_rules, list):
            if not all(isinstance(p, str) for p in raw_custom_rules):
                raise ValueError("'custom-rules' must be a list of strings (file paths)")
            custom_rules = raw_custom_rules
        else:
            raise ValueError(
                f"'custom-rules' must be a list, got {type(raw_custom_rules).__name__}"
            )

        if raw_exclude is None:
            exclude_patterns = list(_DEFAULT_EXCLUDE_PATTERNS)
        elif isinstance(raw_exclude, list):
            if not all(isinstance(p, str) for p in raw_exclude):
                raise ValueError("'exclude' must be a list of strings (glob patterns)")
            exclude_patterns = raw_exclude
        else:
            raise ValueError(f"'exclude' must be a list, got {type(raw_exclude).__name__}")

        raw_content_paths = data.get("content-paths")
        if raw_content_paths is None:
            content_paths: List[str] = []
        elif isinstance(raw_content_paths, list):
            if not all(isinstance(p, str) for p in raw_content_paths):
                raise ValueError("'content-paths' must be a list of strings (glob patterns)")
            content_paths = raw_content_paths
        else:
            raise ValueError(
                "'content-paths' must be a list of strings (glob patterns), "
                f"got {type(raw_content_paths).__name__}"
            )

        if raw_strict is None:
            strict = False
        elif isinstance(raw_strict, bool):
            strict = raw_strict
        else:
            raise ValueError(f"'strict' must be a boolean, got {type(raw_strict).__name__}")

        raw_plugins = data.get("plugins")
        plugins_enabled = True
        disabled_plugins: List[str] = []
        if raw_plugins is None:
            pass
        elif isinstance(raw_plugins, bool):
            # Shorthand: ``plugins: false`` disables all rule plugins.
            plugins_enabled = raw_plugins
        elif isinstance(raw_plugins, dict):
            unknown_plugin_keys = set(raw_plugins) - {"enabled", "disable"}
            if unknown_plugin_keys:
                load_warnings.append(
                    "unknown 'plugins' config key(s) ignored: "
                    + ", ".join(sorted(map(str, unknown_plugin_keys)))
                    + ". Known keys: disable, enabled"
                )
            raw_enabled = raw_plugins.get("enabled")
            if raw_enabled is not None:
                if not isinstance(raw_enabled, bool):
                    raise ValueError(
                        f"'plugins.enabled' must be a boolean, got {type(raw_enabled).__name__}"
                    )
                plugins_enabled = raw_enabled
            raw_disable = raw_plugins.get("disable")
            if raw_disable is not None:
                if not isinstance(raw_disable, list) or not all(
                    isinstance(p, str) for p in raw_disable
                ):
                    raise ValueError("'plugins.disable' must be a list of strings (plugin names)")
                disabled_plugins = raw_disable
        else:
            raise ValueError(
                f"'plugins' must be a boolean or a mapping, got {type(raw_plugins).__name__}. "
                "Example:\n  plugins:\n    disable: [some-plugin]"
            )

        return cls(
            version=_DEFAULT_VERSION if raw_version is None else str(raw_version),
            rules=rules,
            custom_rules=custom_rules,
            exclude_patterns=exclude_patterns,
            content_paths=content_paths,
            strict=strict,
            plugins_enabled=plugins_enabled,
            disabled_plugins=disabled_plugins,
            config_dir=config_path.resolve().parent,
            warnings=load_warnings,
        )

    @classmethod
    def default(cls) -> "LinterConfig":
        """Create the default configuration, generated from the rule registry.

        Each rule's defaults come from its class (``Rule.default_enabled``
        and ``Rule.default_severity``) so there is no second hand-maintained
        copy that can drift. Tunable parameters are not materialized here —
        rules fall back to their ``config_schema`` defaults in code.
        """
        from . import __version__
        from .rules.builtin import BUILTIN_RULES

        rules: Dict[str, Dict[str, Any]] = {}
        for rule_class in BUILTIN_RULES:
            rule = rule_class()
            rules[rule.rule_id] = {
                "enabled": rule.default_enabled,
                "severity": rule.default_severity().value,
            }
        return cls(
            version=__version__,
            exclude_patterns=list(_DEFAULT_EXCLUDE_PATTERNS),
            rules=rules,
        )

    @classmethod
    def for_init(cls) -> "LinterConfig":
        """Config for --init: sets version to current release so all rules are active."""
        from . import __version__

        config = cls.default()
        config.version = __version__
        return config

    def get_rule_config(self, rule_id: str) -> Dict[str, Any]:
        """
        Get configuration for a specific rule, merging user overrides
        on top of defaults so unmentioned fields keep their default values.

        Args:
            rule_id: Rule identifier

        Returns:
            Rule configuration dict
        """
        # Deep-copy the cached defaults so callers mutating the merged result
        # (or its nested lists like ``recommended-fields``) cannot corrupt the
        # shared cache.
        defaults = copy.deepcopy(_default_rules().get(rule_id, {}))
        overrides = self.rules.get(rule_id)
        if overrides is None:
            overrides = {}
        merged = {**defaults, **overrides}
        return merged

    def is_rule_enabled(
        self,
        rule_id: str,
        context: "RepositoryContext",
        repo_types=None,
        formats: Optional[Set[str]] = None,
        since_version: str = "0.1.0",
    ) -> bool:
        """
        Check if a rule is enabled for the given context

        Args:
            rule_id: Rule identifier
            context: Repository context
            repo_types: Set of RepositoryType values the rule applies to (None = all)
            formats: Set of detected format constants the rule requires (None = all)
            since_version: Minimum config version required for this rule

        Returns:
            True if rule should run
        """
        enabled, _reason = self.rule_enabled_reason(
            rule_id, context, repo_types, formats, since_version
        )
        return enabled

    def rule_enabled_reason(
        self,
        rule_id: str,
        context: "RepositoryContext",
        repo_types=None,
        formats: Optional[Set[str]] = None,
        since_version: str = "0.1.0",
    ) -> Tuple[bool, str]:
        """
        Determine whether a rule is enabled and why.

        Same logic as :meth:`is_rule_enabled`, but also returns a
        human-readable reason — used by ``skillsaw explain`` to show the
        effective config state.

        Returns:
            Tuple of (enabled, reason)
        """
        user_overrides = self.rules.get(rule_id, {})
        has_explicit_enabled = "enabled" in user_overrides
        if has_explicit_enabled:
            explicit = user_overrides["enabled"]
            if explicit is True:
                return True, "enabled: true set in config"
            if explicit is False:
                return False, "enabled: false set in config"
            # enabled: "auto" falls through to version gate + auto logic below
        else:
            # Any non-enabled override (e.g. severity) without an explicit
            # ``enabled`` key on a disabled-by-default rule implies the user
            # wants it active.  We must NOT do this for ``enabled: "auto"``
            # rules — those rely on repo-type / format detection.
            if user_overrides:
                default_enabled = _default_rules().get(rule_id, {}).get("enabled", True)
                if default_enabled is False:
                    return True, "configured in config (overrides disabled-by-default)"
                # For "auto" rules, non-enabled overrides don't change
                # activation — fall through to version gate + auto logic.

        # Any explicit user override (enabled or otherwise) implies the user
        # wants this rule, so skip the version gate.
        has_user_overrides = bool(user_overrides)

        if not has_user_overrides and self.version:
            if _parse_version(self.version) < _parse_version(since_version):
                return False, (
                    f"config version {self.version} is older than the rule "
                    f"(since {since_version}) — bump version in config to enable"
                )

        rule_config = self.get_rule_config(rule_id)
        enabled = rule_config.get("enabled", True)

        if enabled == "auto":
            if repo_types is None and formats is None:
                return True, "enabled: auto (applies to all repo types)"
            if repo_types is not None and repo_types & context.repo_types:
                matched = sorted(t.value for t in repo_types & context.repo_types)
                return True, f"enabled: auto — detected repo type: {', '.join(matched)}"
            if formats is not None and formats & context.detected_formats:
                matched = sorted(formats & context.detected_formats)
                return True, f"enabled: auto — detected format: {', '.join(matched)}"
            return False, "enabled: auto — no matching repo type or format detected"

        if bool(enabled):
            return True, "enabled by default"
        return False, "disabled by default"

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization"""
        d: Dict[str, Any] = {}
        if self.version:
            d["version"] = self.version
        d["rules"] = self.rules
        d["custom-rules"] = self.custom_rules
        d["exclude"] = self.exclude_patterns
        d["strict"] = self.strict
        if self.content_paths:
            d["content-paths"] = self.content_paths
        if not self.plugins_enabled or self.disabled_plugins:
            plugins: Dict[str, Any] = {}
            if not self.plugins_enabled:
                plugins["enabled"] = False
            if self.disabled_plugins:
                plugins["disable"] = self.disabled_plugins
            d["plugins"] = plugins
        return d

    def save(self, config_path: Path):
        """Save configuration to file with rule descriptions and config options as comments"""
        from .rules.builtin import BUILTIN_RULES

        descriptions = {}
        schemas = {}
        for rule_class in BUILTIN_RULES:
            rule = rule_class()
            descriptions[rule.rule_id] = rule.description
            if rule.config_schema:
                schemas[rule.rule_id] = rule.config_schema

        with open(config_path, "w", encoding="utf-8") as f:
            f.write("# skillsaw configuration\n")
            f.write("# https://github.com/stbenjam/skillsaw\n\n")
            if self.version:
                f.write(f'version: "{self.version}"\n\n')
            f.write("rules:\n")
            for rule_id, rule_config in self.rules.items():
                desc = descriptions.get(rule_id, "")
                if desc:
                    f.write(f"\n  # {desc}\n")
                f.write(f"  {rule_id}:\n")
                for key, value in rule_config.items():
                    yaml_val = self._yaml_value(value)
                    if yaml_val.startswith("\n"):
                        f.write(f"    {key}:{yaml_val}\n")
                    else:
                        f.write(f"    {key}: {yaml_val}\n")
                # Write commented-out config_schema options not already in config
                schema = schemas.get(rule_id, {})
                for param_name, param_info in schema.items():
                    if param_name not in rule_config:
                        default = param_info.get("default")
                        yaml_val = self._yaml_value(default, indent=2)
                        if yaml_val.startswith("\n"):
                            # Multi-line value: comment out each line
                            lines = yaml_val.lstrip("\n").split("\n")
                            f.write(f"    # {param_name}:\n")
                            for line in lines:
                                f.write(f"    # {line}\n")
                        else:
                            f.write(f"    # {param_name}: {yaml_val}\n")

            f.write("\n# Load custom rules from these files\n")
            self._write_field(f, "custom-rules", self.custom_rules)
            f.write(
                "\n# Rule plugins (pip-installed packages that add rules)\n"
                "# https://skillsaw.org/plugins/\n"
            )
            if not self.plugins_enabled or self.disabled_plugins:
                self._write_field(
                    f,
                    "plugins",
                    {
                        "enabled": self.plugins_enabled,
                        "disable": self.disabled_plugins,
                    },
                )
            else:
                f.write("# plugins:\n")
                f.write("#     enabled: true\n")
                f.write('#     disable: ["some-plugin-name"]\n')
            f.write("\n# Exclude patterns (glob format)\n")
            f.write("# Use exclude: [] to disable all excludes including defaults\n")
            user_excludes = [p for p in self.exclude_patterns if p not in _DEFAULT_EXCLUDE_PATTERNS]
            if user_excludes:
                self._write_field(f, "exclude", user_excludes)
            else:
                f.write("exclude:\n")
                for pat in _DEFAULT_EXCLUDE_PATTERNS:
                    f.write(f'    # - "{pat}"\n')
            f.write("\n# Additional markdown files to run content rules on (glob format)\n")
            self._write_field(f, "content-paths", self.content_paths)
            f.write("\n# Treat warnings as errors\n")
            f.write(f"strict: {self._yaml_value(self.strict)}\n")

    def _write_field(self, f, key: str, value: Any):
        """Helper to write a YAML field to the file."""
        val = self._yaml_value(value)
        if val.startswith("\n"):
            f.write(f"{key}:{val}\n")
        else:
            f.write(f"{key}: {val}\n")

    @staticmethod
    def _yaml_scalar(value: str) -> str:
        """Serialize a string scalar through PyYAML's emitter.

        Delegating quoting/escaping to the same library that reparses the
        file means the output can never drift out of sync with the parser:
        YAML-special characters, comment/mapping indicators, control
        characters, and strings that would resolve to other types under
        implicit typing ("no", "123", "12:34:56", ...) all come back as the
        same string. Double-quoted style is forced for control characters so
        the result always stays on a single line.
        """
        style = '"' if any(ord(c) < 0x20 for c in value) else None
        dumped = yaml.safe_dump(value, default_flow_style=True, default_style=style, width=2**31)
        return dumped.rstrip("\n").removesuffix("\n...")

    @staticmethod
    def _yaml_value(value, indent=4):
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            if not value:
                return "[]"
            pad = " " * indent
            items = []
            for item in value:
                rendered = LinterConfig._yaml_value(item, indent + 2)
                items.append(f"{pad}- {rendered}")
            return "\n" + "\n".join(items)
        if isinstance(value, dict):
            if not value:
                return "{}"
            pad = " " * indent
            lines = []
            for k, v in value.items():
                rendered = LinterConfig._yaml_value(v, indent + 2)
                if rendered.startswith("\n"):
                    lines.append(f"{pad}{k}:{rendered}")
                else:
                    lines.append(f"{pad}{k}: {rendered}")
            return "\n" + "\n".join(lines)
        if isinstance(value, str):
            return LinterConfig._yaml_scalar(value)
        return str(value)


def find_config(start_path: Path) -> Optional[Path]:
    """
    Find config file by walking up the directory tree.

    Checks for .skillsaw.yaml first, then falls back to .claudelint.yaml
    for backward compatibility.
    """
    current = start_path.resolve()

    # Walk up to and *including* the filesystem root, so a config placed at
    # ``/`` (common in containers where the repo is mounted at the root) is
    # still found.  ``current.parents`` does not include ``current`` itself.
    for directory in (current, *current.parents):
        for name in (
            ".skillsaw.yaml",
            ".skillsaw.yml",
            ".claudelint.yaml",
            ".claudelint.yml",
        ):
            config_file = directory / name
            if config_file.exists():
                return config_file

    return None


@functools.lru_cache(maxsize=1)
def _default_rules() -> Dict[str, Dict[str, Any]]:
    """Memoised default rule mapping for the hot read path.

    ``LinterConfig.default()`` rebuilds the entire ~60-rule dict on every call,
    and ``get_rule_config`` / ``rule_enabled_reason`` are invoked per rule and
    once per violation during filtering.  The defaults are deterministic, so we
    cache them.  Callers only read this mapping (``get_rule_config`` returns a
    freshly merged dict), so sharing the instance is safe.
    """
    return LinterConfig.default().rules
