"""Attach the native Claude rules inventory through the shared tree guards."""

from skillsaw.blocks.claude_rules import ClaudeRuleFileNode
from skillsaw.discovery.excludes import is_root_or_ancestor_excluded


def attach_claude_rule_files(state, directory, readable_matches):
    if is_root_or_ancestor_excluded(
        directory, state.context.root_path, state.context.is_path_excluded
    ):
        return
    for path in readable_matches(directory, "**/*"):
        state.add_parser_block(
            state.root,
            path,
            ClaudeRuleFileNode,
            reserve_extra_content=False,
            file_inventory=True,
        )
