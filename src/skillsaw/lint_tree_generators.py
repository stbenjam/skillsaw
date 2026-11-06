"""Attach generator sources, configuration, and conventional consumer roles."""

from skillsaw.blocks import PluginRuleBlock
from skillsaw.blocks.generators import (
    RulerConfigBlock,
    RulerRuleBlock,
    RulesyncConfigBlock,
    RulesyncRuleBlock,
)
from skillsaw.discovery.excludes import is_root_or_ancestor_excluded
from skillsaw.claude_tree import attach_claude_rule_files


def attach_rulesync_claude_rules(state, readable_matches):
    """Attach conventional Claude consumers at nested Rulesync project roots.

    Consumer parsing does not depend on generated ownership: stale output and
    hand-maintained rules alongside it must retain their native checks too.
    """
    context = state.context
    for project in context.generator_projects():
        if project.generator != "rulesync":
            continue
        directory = project.root / ".claude" / "rules"
        if context.in_apm_compiled_dir(directory) or is_root_or_ancestor_excluded(
            directory, context.root_path, context.is_path_excluded
        ):
            continue
        attach_claude_rule_files(state, directory, readable_matches)
        for path in readable_matches(directory, "**/*.md"):
            state.add_parser_block(state.root, path, PluginRuleBlock)


def attach_generator_sources(state):
    for project in state.context.generator_projects():
        ruler = project.generator == "ruler"
        for path in project.rules:
            # A source may also be a native instruction or an alias of a
            # consumer config. Preserve both interpretations: their decoded
            # fields, frontmatter and whole-file views need different checks.
            state.add_parser_block(
                state.root,
                path,
                RulerRuleBlock if ruler else RulesyncRuleBlock,
                preserve_content_aliases=True,
            )


def attach_generator_configs(state):
    """Add independent config parsers after native consumers, before extra prose."""
    for project in state.context.generator_projects():
        ruler = project.generator == "ruler"
        if project.config is not None:
            state.add_parser_block(
                state.root,
                project.config,
                RulerConfigBlock if ruler else RulesyncConfigBlock,
                preserve_content_aliases=True,
            )
