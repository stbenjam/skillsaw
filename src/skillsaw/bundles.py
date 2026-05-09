"""
Rule bundles — named groups of rules that can be enabled/disabled together.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .config import LinterConfig, find_config
from .rules.builtin import BUILTIN_RULES

BUILTIN_BUNDLES: Dict[str, str] = {
    "cursor": "All Cursor MDC rules",
    "copilot": "All Copilot instruction rules",
    "claude": "All Claude Code rules",
    "agents-md": "All AGENTS.md rules",
    "gemini": "All Gemini rules",
    "kiro": "All Kiro rules",
    "apm": "All APM rules",
    "content": "All content intelligence rules",
    "agentskills": "All agentskills.io rules",
    "marketplace": "All marketplace rules",
    "plugin": "All plugin structure rules",
    "all": "Every rule",
}

_BUNDLE_PREFIXES: Dict[str, List[str]] = {
    "cursor": ["cursor-"],
    "copilot": ["copilot-"],
    "claude": ["claude-"],
    "agents-md": ["agents-md-"],
    "gemini": ["gemini-"],
    "kiro": ["kiro-"],
    "apm": ["apm-"],
    "content": ["content-"],
    "agentskills": ["agentskill-"],
    "marketplace": ["marketplace-"],
    "plugin": ["plugin-", "command-", "skill-", "agent-", "hooks-", "mcp-", "rules-"],
}


def _all_rule_ids() -> List[str]:
    return [rc().rule_id for rc in BUILTIN_RULES]


def get_bundle_rules(bundle: str) -> Optional[List[str]]:
    if bundle not in BUILTIN_BUNDLES:
        return None
    if bundle == "all":
        return _all_rule_ids()
    prefixes = _BUNDLE_PREFIXES.get(bundle, [])
    all_ids = _all_rule_ids()
    return [rid for rid in all_ids if any(rid.startswith(p) for p in prefixes)]


def is_bundle(name: str) -> bool:
    return name in BUILTIN_BUNDLES


def is_rule(name: str) -> bool:
    all_ids = _all_rule_ids()
    return name in all_ids


def resolve_names(name: str) -> Tuple[List[str], bool]:
    """Resolve a name to a list of rule IDs. Returns (rule_ids, is_bundle)."""
    if is_bundle(name):
        return get_bundle_rules(name), True
    if is_rule(name):
        return [name], False
    return [], False


def _load_yaml_preserving(path: Path) -> Tuple[str, dict]:
    """Load YAML file, returning raw text and parsed dict."""
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
    else:
        raw = ""
        data = {}
    return raw, data


def _ensure_config(target: Path) -> Path:
    config_path = find_config(target)
    if config_path:
        return config_path
    config_path = target / ".skillsaw.yaml"
    config = LinterConfig.for_init()
    config.save(config_path)
    return config_path


def enable_rules(
    rule_ids: List[str],
    target: Path,
    dry_run: bool = False,
) -> List[Tuple[str, str]]:
    """
    Enable rules in .skillsaw.yaml. Returns list of (rule_id, action) tuples
    where action is 'enabled' or 'already enabled'.
    """
    config_path = _ensure_config(target)
    _, data = _load_yaml_preserving(config_path)
    rules_section = data.get("rules", {})

    results = []
    changed = False
    for rid in rule_ids:
        current = rules_section.get(rid, {})
        current_enabled = current.get("enabled", "auto")
        if current_enabled is True or current_enabled == "auto":
            results.append((rid, "already enabled"))
            continue
        if rid in rules_section:
            rules_section[rid]["enabled"] = "auto"
        else:
            rules_section[rid] = {"enabled": "auto"}
        results.append((rid, "enabled"))
        changed = True

    if changed and not dry_run:
        data["rules"] = rules_section
        config = LinterConfig(
            rules=data.get("rules", {}),
            custom_rules=data.get("custom-rules", []),
            exclude_patterns=data.get("exclude", []),
            strict=data.get("strict", False),
        )
        config.save(config_path)

    return results


def disable_rules(
    rule_ids: List[str],
    target: Path,
    dry_run: bool = False,
) -> List[Tuple[str, str]]:
    """
    Disable rules in .skillsaw.yaml. Returns list of (rule_id, action) tuples
    where action is 'disabled' or 'already disabled'.
    """
    config_path = _ensure_config(target)
    _, data = _load_yaml_preserving(config_path)
    rules_section = data.get("rules", {})

    results = []
    changed = False
    for rid in rule_ids:
        current = rules_section.get(rid, {})
        current_enabled = current.get("enabled", "auto")
        if current_enabled is False:
            results.append((rid, "already disabled"))
            continue
        if rid in rules_section:
            rules_section[rid]["enabled"] = False
        else:
            rules_section[rid] = {"enabled": False}
        results.append((rid, "disabled"))
        changed = True

    if changed and not dry_run:
        data["rules"] = rules_section
        config = LinterConfig(
            rules=data.get("rules", {}),
            custom_rules=data.get("custom-rules", []),
            exclude_patterns=data.get("exclude", []),
            strict=data.get("strict", False),
        )
        config.save(config_path)

    return results
