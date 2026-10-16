"""Pinned authored-source contracts, not target compilers.

Ruler v0.3.44 (658d1bc), src/core/ConfigLoader.ts and FileSystemUtils.ts.
Rulesync v32.0.0 (01118a9), src/config/config.ts and
src/features/rules/rulesync-rule.ts. See docs/generators.md for evidence.
"""

from __future__ import annotations

import math
import re
from typing import Any, NamedTuple

import yaml

from skillsaw.utils import _SAFE_LOADER, FRONTMATTER_RE_EMPTY_OK

STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}
STRINGS = {"type": "array", "items": STRING}


def object_schema(properties, *, additional=True):
    return {"type": "object", "properties": properties, "additionalProperties": additional}


_MCP_TOGGLE = object_schema(
    {
        "enabled": BOOLEAN,
        "merge_strategy": {"enum": ["merge", "overwrite"]},
    },
    additional=False,
)
_SERVERS = {"type": "object", "additionalProperties": {"type": "object"}}
_AGENT = object_schema(
    {
        "enabled": BOOLEAN,
        "output_path": STRING,
        "output_path_instructions": STRING,
        "output_path_config": STRING,
        "mcp": _MCP_TOGGLE,
        "mcp_servers": _SERVERS,
    },
    additional=False,
)
_SUBAGENTS = {key: BOOLEAN for key in ("enabled", "include_in_rules", "cleanup_orphaned")}
RULER_CONFIG = object_schema(
    {
        "default_agents": STRINGS,
        "agents": object_schema(_SUBAGENTS, additional=_AGENT),
        "mcp": _MCP_TOGGLE,
        "mcp_servers": _SERVERS,
        "gitignore": object_schema({"enabled": BOOLEAN, "local": BOOLEAN}, additional=False),
        "backup": object_schema({"enabled": BOOLEAN}, additional=False),
        "skills": object_schema({"enabled": BOOLEAN}, additional=False),
        "subagents": object_schema(_SUBAGENTS, additional=False),
        "nested": BOOLEAN,
    },
    additional=False,
)

# Only the common authored fields and the two modular copy targets. Unknown
# target names/options are left to the pinned generator's own validation.
RULESYNC_RULE = object_schema(
    {
        "root": BOOLEAN,
        "localRoot": BOOLEAN,
        "targets": STRINGS,
        "description": STRING,
        "globs": STRINGS,
        "claudecode": object_schema({"paths": STRINGS}),
        "cursor": object_schema({"alwaysApply": BOOLEAN, "description": STRING, "globs": STRINGS}),
        "agentsmd": object_schema({"subprojectPath": STRING}),
    }
)
RULESYNC_CONFIG = object_schema(
    {
        "$schema": STRING,
        "targets": {"anyOf": [STRINGS, {"type": "object"}]},
        "features": STRINGS,
        "outputRoots": {
            "anyOf": [
                STRINGS,
                {
                    "type": "object",
                    "additionalProperties": {
                        "anyOf": [STRING, STRINGS],
                    },
                },
            ]
        },
        "inputRoot": STRING,
        "inputRoots": {**STRINGS, "minItems": 1},
        **{
            key: BOOLEAN
            for key in (
                "verbose",
                "delete",
                "global",
                "silent",
                "dryRun",
                "check",
                "simulateCommands",
                "simulateSubagents",
                "simulateSkills",
                "preserveUnownedHooks",
                "deriveSubprojectPathFromGlobs",
                "gitignoreTargetsOnly",
            )
        },
    }
)


def schema_problems(data, schema):
    """Concise field locations; never echo config values (which may be secrets)."""
    from jsonschema import Draft7Validator

    return [
        (
            tuple(error.absolute_path),
            (
                f"{'.'.join(map(str, error.absolute_path)) or 'document'}: "
                f"expected {error.validator_value}"
                if error.validator == "type"
                else f"{'.'.join(map(str, error.absolute_path)) or 'document'}: invalid {error.validator}"
            ),
        )
        for error in Draft7Validator(schema).iter_errors(data)
    ]


def _rulesync_scalar_key(value):
    """Normalize simple scalar keys, including JavaScript binary64 rounding."""
    if value is True or value is False:
        return str(value).lower()
    if value is None:
        return "null"
    if not isinstance(value, (int, float)):
        return value
    try:
        number = float(value)
    except OverflowError:
        number = math.inf if value > 0 else -math.inf
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "Infinity" if number > 0 else "-Infinity"
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    mantissa, _, exponent = repr(abs(number)).partition("e")
    mantissa = mantissa.removesuffix(".0")
    if not exponent:
        return sign + mantissa
    power = int(exponent)
    # Number.toString uses fixed notation in [1e-6, 1e21), retaining the
    # shortest decimal digits rather than the exact integer of the float.
    if -6 <= power < 21:
        whole, _, fraction = mantissa.partition(".")
        digits = whole + fraction
        point = len(whole) + power
        if point <= 0:
            return sign + "0." + "0" * -point + digits
        if point >= len(digits):
            return sign + digits + "0" * (point - len(digits))
        return sign + digits[:point] + "." + digits[point:]
    return f"{sign}{mantissa}e{power:+d}"


class _RulesyncLoader(_SAFE_LOADER):
    portable_keys = True

    # js-yaml's default schema accepts true/false, not YAML 1.1's yes/no/on/off.
    yaml_implicit_resolvers = {
        key: [(tag, pattern) for tag, pattern in values if tag != "tag:yaml.org,2002:bool"]
        for key, values in _SAFE_LOADER.yaml_implicit_resolvers.items()
    }

    def construct_property_key(self, node):
        """Match js-yaml's storeMappingPair without expanding alias graphs."""
        value = self.construct_object(node)
        if isinstance(node, yaml.MappingNode):
            return "[object Object]"
        if isinstance(node, yaml.SequenceNode):
            parts = []
            for item in node.value:
                # js-yaml rejects nested arrays here to prevent explosive
                # stringification of aliases; mapping keys use a constant.
                if isinstance(item, yaml.SequenceNode):
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping key",
                        node.start_mark,
                        "nested arrays are not supported inside keys",
                        item.start_mark,
                    )
                parts.append(
                    ""
                    if item.tag == "tag:yaml.org,2002:null"
                    else self.construct_property_key(item)
                )
            # A nonportable element makes the entire array key opaque. Python
            # str(date/bytes) would invent collisions with ordinary strings.
            return ",".join(parts) if all(isinstance(part, str) for part in parts) else tuple(parts)
        key = _rulesync_scalar_key(value)
        if not isinstance(key, str):
            # Date.toString depends on the generator's runtime time zone.
            # Timestamp and binary keys are outside the portable subset;
            # retain their values, without inventing property spellings.
            self.portable_keys = False
        return key

    def flatten_mapping(self, node):
        # js-yaml rejects duplicate explicit keys; a YAML merge followed by an
        # explicit override is valid and is left to SafeLoader's merge logic.
        # SafeLoader mutates anchored mappings during merge flattening. Check
        # each original mapping once, before inherited keys are inserted.
        checked = self.__dict__.setdefault("_duplicate_checked_nodes", set())
        if node in checked:
            return super().flatten_mapping(node)
        checked.add(node)
        seen = set()
        for key, _value in node.value:
            if key.tag == "tag:yaml.org,2002:merge":
                continue
            value = self.construct_property_key(key)
            # js-yaml stores object keys as strings, so true and 1 are distinct
            # even though Python's bool/int keys compare equal. Quoted scalar
            # spellings still collide with their corresponding native values.
            duplicate = value in seen
            seen.add(value)
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "duplicate mapping key",
                    key.start_mark,
                )
        return super().flatten_mapping(node)

    def construct_mapping(self, node, deep=False):
        """Normalize keys before dict insertion can collapse True and 1."""
        if not isinstance(node, yaml.MappingNode):
            return super().construct_mapping(node, deep=deep)
        self.flatten_mapping(node)
        return {
            self.construct_property_key(key): self.construct_object(value, deep=deep)
            for key, value in node.value
        }


_RulesyncLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)

# The Rulesync parser accepts exponent scalars without a decimal point
# or explicit sign; PyYAML needs this additional resolver.
_RulesyncLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^(?:[-+]?(?:0|[1-9][0-9_]*)(?:\.[0-9_]*)?|\.[0-9_]+)[eE][-+]?[0-9]+$"),
    list("-+0123456789."),
)


class RulesyncFrontmatter(NamedTuple):
    data: dict[str, Any] | None
    error: str | None
    error_line: int | None
    body: str
    line_offset: int
    key_lines: dict[str, int]
    portable_keys: bool = True


def parse_rulesync_frontmatter(content):
    """Parse conventional YAML frontmatter, retaining honest body line offsets.

    Rulesync drops null object fields and array entries before validation.
    Noncanonical gray-matter fences and target-specific extensions are outside
    this validator's scope.
    """
    match = FRONTMATTER_RE_EMPTY_OK.match(content.lstrip("\ufeff"))
    if match is None:
        return RulesyncFrontmatter(None, None, None, content, 0, {})
    normalized = content.lstrip("\ufeff")
    body = normalized[match.end() :]
    offset = normalized[: match.end()].count("\n")
    loader = _RulesyncLoader(match.group(1))
    key_lines = {}
    try:
        node = loader.get_single_node()
        # Save explicit key positions before SafeLoader flattens merge keys.
        # The same constructors and normalization serve data and line lookup.
        if isinstance(node, yaml.MappingNode):
            key_lines = {
                loader.construct_property_key(key): key.start_mark.line + 2
                for key, _value in node.value
                if key.tag != "tag:yaml.org,2002:merge"
            }
        data = loader.construct_document(node) if node is not None else None
    except (yaml.YAMLError, ValueError, RecursionError) as error:
        mark = getattr(error, "problem_mark", None)
        return RulesyncFrontmatter(
            None, "Invalid YAML frontmatter", mark.line + 2 if mark else None, body, offset, {}
        )
    finally:
        loader.dispose()
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return RulesyncFrontmatter(None, "Frontmatter must be a mapping", 2, body, offset, {})
    # Only remove nulls in the fields we interpret, without traversing arbitrary
    # YAML alias graphs. Those graphs remain the generator's validation job.
    data = {key: value for key, value in data.items() if value is not None}
    for key in ("cursor", "claudecode", "agentsmd"):
        if isinstance(data.get(key), dict):
            data[key] = {k: v for k, v in data[key].items() if v is not None}
    for mapping, keys in (
        (data, ("targets", "globs")),
        (data.get("cursor"), ("globs",)),
        (data.get("claudecode"), ("paths",)),
    ):
        if isinstance(mapping, dict):
            for key in keys:
                if isinstance(mapping.get(key), list):
                    mapping[key] = [item for item in mapping[key] if item is not None]
    return RulesyncFrontmatter(data, None, None, body, offset, key_lines, loader.portable_keys)
