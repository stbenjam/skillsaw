"""Consumer-specific scalar construction for Devin's native frontmatter."""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from skillsaw.formats import devin
from skillsaw.utils import FRONTMATTER_RE_EMPTY_OK, _SAFE_LOADER, read_text

_YAML = "tag:yaml.org,2002:"
_TEXT_TAGS = frozenset(_YAML + tag for tag in ("str", "bool", "int", "float", "timestamp", "null"))


def _string(node, *, optional=False):
    # serde_yaml's typed strings preserve the source scalar, including numeric
    # spelling. Option<String> alone treats an unquoted null as absent.
    if not isinstance(node, yaml.ScalarNode) or node.tag not in _TEXT_TAGS:
        return node
    if optional and node.tag == _YAML + "null":
        return node
    return yaml.ScalarNode(_YAML + "str", node.value, node.start_mark, node.end_mark, node.style)


def _string_list(node):
    if not isinstance(node, yaml.SequenceNode):
        return node
    return yaml.SequenceNode(
        node.tag,
        [_string(item) for item in node.value],
        node.start_mark,
        node.end_mark,
        node.flow_style,
    )


def _untyped_scalar(node):
    # The untagged allowed-tools scalar accepts strings, but rejects actual
    # numbers and booleans. YAML 1.1 yes/no/on/off and timestamps are strings
    # in Devin; only true/false are valid booleans for subagent.
    if isinstance(node, yaml.ScalarNode) and (
        node.tag == _YAML + "timestamp"
        or (node.tag == _YAML + "bool" and node.value.lower() not in {"true", "false"})
    ):
        return _string(node)
    return node


def _native_key(node):
    # Devin treats YAML's merge spelling as an unknown field, not an instruction
    # to import fields from another mapping. Ordinary aliases still work.
    if isinstance(node, yaml.ScalarNode) and node.tag == _YAML + "merge":
        return yaml.ScalarNode(
            _YAML + "str", node.value, node.start_mark, node.end_mark, node.style
        )
    return node


def _native_fields(node, *, skill):
    pairs = []
    for key, value in node.value:
        name = key.value if isinstance(key, yaml.ScalarNode) else None
        if name in (devin.SKILL_STRING_FIELDS if skill else {"trigger", "description"}):
            value = _string(value, optional=True)
        elif name in ({"allowed-tools", "triggers"} if skill else {"globs"}):
            value = _string_list(value)
            if skill and name == "allowed-tools":
                value = _untyped_scalar(value)
        elif skill and name == "subagent":
            value = _untyped_scalar(value)
        elif skill and name == "permissions" and isinstance(value, yaml.MappingNode):
            permissions = [
                (
                    _native_key(key),
                    (
                        _string_list(item)
                        if isinstance(key, yaml.ScalarNode) and key.value in devin.PERMISSION_KEYS
                        else item
                    ),
                )
                for key, item in value.value
            ]
            value = yaml.MappingNode(
                value.tag, permissions, value.start_mark, value.end_mark, value.flow_style
            )
        pairs.append((_native_key(key), value))
    # Clone nodes rather than retagging aliases in place: a known field can
    # share an anchor with an unknown extension whose construction is unchanged.
    return yaml.MappingNode(node.tag, pairs, node.start_mark, node.end_mark, node.flow_style)


def _duplicate_field(node, known_fields, *, prefix=""):
    seen = {}
    for key, _value in node.value:
        if not isinstance(key, yaml.ScalarNode) or key.value not in known_fields:
            continue
        if key.value in seen:
            # An aliased key retains its anchor's source mark. Do not report
            # that earlier line as though it were the repeated occurrence.
            line = key.start_mark.line + 2 if key is not seen[key.value] else None
            return prefix + key.value, line
        seen[key.value] = key
    return None


def parse_devin_frontmatter(
    content: str, *, skill: bool = False
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
    """Read native fields with one safe LibYAML-backed parse and source marks."""
    if not content.startswith("---"):
        return None, None, None, content, 0
    error = "Invalid frontmatter (malformed YAML or missing closing ---)"
    match = FRONTMATTER_RE_EMPTY_OK.match(content)
    if match is None:
        return None, error, None, content, 0
    loader = _SAFE_LOADER(match.group(1))
    try:
        node = loader.get_single_node()
        if node is None:
            data = {}
        elif isinstance(node, yaml.MappingNode):
            known_fields = (
                devin.SKILL_FRONTMATTER_FIELDS if skill else devin.RULE_FRONTMATTER_FIELDS
            )
            duplicate = _duplicate_field(node, known_fields)
            if skill and duplicate is None:
                for key, value in node.value:
                    if (
                        isinstance(key, yaml.ScalarNode)
                        and key.value == "permissions"
                        and isinstance(value, yaml.MappingNode)
                    ):
                        duplicate = _duplicate_field(
                            value, devin.PERMISSION_KEYS, prefix="permissions."
                        )
                        if duplicate is not None:
                            break
            if duplicate is not None:
                name, line = duplicate
                return None, f"Duplicate frontmatter field '{name}'", line, content, 0
            data = loader.construct_document(_native_fields(node, skill=skill))
        else:
            return None, error, None, content, 0
    except (yaml.YAMLError, ValueError, RecursionError) as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 2 if mark is not None else None
        return None, error, line, content, 0
    finally:
        loader.dispose()
    return data, None, None, content[match.end() :], content[: match.end()].count("\n")


def read_devin_frontmatter(
    path: Path, *, skill: bool = False
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[int], str, int]:
    content = read_text(path)
    if content is None:
        return None, f"Failed to read file: {path}", None, "", 0
    return parse_devin_frontmatter(content, skill=skill)
