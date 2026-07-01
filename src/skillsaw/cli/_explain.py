"""Handler for the ``skillsaw explain`` subcommand."""

from __future__ import annotations

import sys

from ..config import LinterConfig
from ..context import RepositoryContext
from ._config import load_config
from ._helpers import _ansi_colors


def _run_explain(args):
    from ..rules.builtin import BUILTIN_RULES
    from ..rule_docs import load_rule_docs, rule_doc_url

    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)
    if args.config and not args.config.exists():
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    rule_class = None
    known_ids = []
    for candidate in BUILTIN_RULES:
        rule = candidate()
        known_ids.append(rule.rule_id)
        if rule.rule_id == args.rule_id:
            rule_class = candidate
            break

    if rule_class is None:
        print(f"Error: Unknown rule '{args.rule_id}'", file=sys.stderr)
        import difflib

        close = difflib.get_close_matches(args.rule_id, known_ids, n=3)
        if close:
            print(f"Did you mean: {', '.join(close)}?", file=sys.stderr)
        print("Run `skillsaw list-rules` to see all rules.", file=sys.stderr)
        sys.exit(1)

    c = _ansi_colors()
    defaults = LinterConfig.default()
    default_rule = rule_class(defaults.get_rule_config(args.rule_id))
    default_enabled = defaults.get_rule_config(args.rule_id).get("enabled", True)

    fix_types = []
    if default_rule.supports_autofix:
        fix_types.append("auto")
    autofix_label = ", ".join(fix_types) if fix_types else "none"
    llm_fix_label = "yes" if default_rule.llm_fix_prompt is not None else "no"

    header_meta = (
        f"{default_rule.severity.value}, autofix: {autofix_label}, "
        f"llm-fix: {llm_fix_label}, since {default_rule.since}"
    )
    print(f"{c['bold']}{args.rule_id}{c['reset']} ({header_meta})")
    print()
    print(default_rule.description)

    long_docs = load_rule_docs(args.rule_id)
    if long_docs:
        print()
        print(long_docs)

    if default_rule.repo_types:
        repo_types_str = ", ".join(sorted(t.value for t in default_rule.repo_types))
        print()
        print(f"{c['bold']}Applies to repo types:{c['reset']} {repo_types_str}")

    print()
    print(f"{c['bold']}Configuration{c['reset']} (.skillsaw.yaml):")
    print("  rules:")
    print(f"    {args.rule_id}:")
    enabled_str = LinterConfig._yaml_value(default_enabled)
    print(f"      enabled: {enabled_str}        # true | false | auto")
    print(f"      severity: {default_rule.severity.value}     " f"# error | warning | info")
    for param_name, param_info in default_rule.config_schema.items():
        default_val = LinterConfig._yaml_value(param_info.get("default"), indent=8)
        desc = param_info.get("description", "")
        if default_val.startswith("\n"):
            print(f"      {param_name}:  # {desc}{default_val}")
        else:
            print(f"      {param_name}: {default_val}  # {desc}")

    config, config_path = load_config(args, args.path)
    context = RepositoryContext(
        args.path,
        exclude_patterns=config.exclude_patterns,
        content_paths=config.content_paths,
    )
    config_label = str(config_path) if config_path else "builtin defaults"

    enabled, reason = config.rule_enabled_reason(
        args.rule_id,
        context,
        default_rule.repo_types,
        default_rule.formats,
        since_version=default_rule.since,
    )
    try:
        effective_rule = rule_class(config.get_rule_config(args.rule_id))
        effective_severity = effective_rule.severity.value
    except ValueError:
        effective_severity = "(invalid severity in config)"

    state = f"{c['green']}enabled{c['reset']}" if enabled else f"{c['red']}disabled{c['reset']}"
    print()
    print(f"{c['bold']}Effective in {args.path.resolve()}{c['reset']} ({config_label}):")
    print(f"  {state} — {reason}")
    if enabled:
        print(f"  severity: {effective_severity}")

    print()
    print(f"{c['bold']}Docs:{c['reset']} {rule_doc_url(args.rule_id)}")
    sys.exit(0)
