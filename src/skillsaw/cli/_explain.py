"""Handler for the ``skillsaw explain`` subcommand."""

from __future__ import annotations

import sys

from ..config import LinterConfig
from ..context import RepositoryContext
from ._config import load_config
from ._helpers import _ansi_colors


def _run_explain(args):
    from ..rule_docs import find_rule_class, load_rule_docs, rule_doc_url

    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)
    if args.config and not args.config.exists():
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    rule_class, plugin_name, known_ids = find_rule_class(args.rule_id)

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

    autofix_label = "auto" if default_rule.supports_autofix else "none"

    header_meta = (
        f"{default_rule.severity.value}, autofix: {autofix_label}, " f"since {default_rule.since}"
    )
    if plugin_name:
        header_meta += f", plugin: {plugin_name}"
    print(f"{c['bold']}{args.rule_id}{c['reset']} ({header_meta})")
    print()
    print(default_rule.description)

    long_docs = load_rule_docs(args.rule_id)
    if long_docs:
        print()
        print(long_docs)

    if default_rule.repo_types:
        # repo_types may mix RepositoryType members with plugin type names.
        repo_types_str = ", ".join(sorted(getattr(t, "value", t) for t in default_rule.repo_types))
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

    # Plugin-contributed repo types must be detected for the effective state
    # to match a real lint run (rules may scope to them via string entries).
    if config.plugins_enabled:
        from ..plugins import load_plugins, register_extensions

        # A crashed or colliding detector would otherwise silently read as
        # "no matching repo type detected" — surface it like `skillsaw tree`.
        for problem in register_extensions(
            context, load_plugins(disabled=set(config.disabled_plugins))
        ):
            print(f"Warning: {problem.message}", file=sys.stderr)

    enabled, reason = config.rule_enabled_reason(
        args.rule_id,
        context,
        default_rule.repo_types,
        default_rule.formats,
        since_version=default_rule.since,
        # Plugin rules have no entry in the builtin defaults registry; their
        # class-level default drives activation (None for builtins).
        default_enabled=default_rule.default_enabled if plugin_name else None,
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

    if plugin_name is None:
        # Plugin rules have no page on the skillsaw documentation site.
        print()
        print(f"{c['bold']}Docs:{c['reset']} {rule_doc_url(args.rule_id)}")
    sys.exit(0)
