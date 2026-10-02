"""Attach declared Goose recipe roots and their contained local subrecipes."""

from skillsaw.blocks.goose import GooseRecipeBlock
from skillsaw.discovery.goose import existing_subrecipe, local_subrecipe, recipe_files
from skillsaw.formats.goose import PROJECT_CONFIG_FILES


def attach_goose_recipes(state, root) -> None:
    context = state.context
    pending = []
    if context.goose_recipes_forced:
        pending.extend(
            (path, context.root_path)
            for path in recipe_files(context.root_path)
            if path.name not in PROJECT_CONFIG_FILES
        )
    for directory in context.agent_tool_dirs(".goose"):
        pending.extend((path, directory.parent) for path in recipe_files(directory / "recipes"))
    while pending:
        path, workspace = pending.pop()
        block = state.add_parser_block(root, path, GooseRecipeBlock)
        if block is None:
            continue
        block.workspace = workspace
        block.children.extend(block.prose_blocks())
        data = block.raw_data
        references = data.get("sub_recipes") if isinstance(data, dict) else None
        if not isinstance(references, list):
            continue
        for entry in references:
            value = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(value, str):
                continue
            target = local_subrecipe(value, path, workspace, state.repo_root, context.resolve_path)
            if existing_subrecipe(target):
                pending.append((target, workspace))
