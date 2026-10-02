"""Goose recipes: v1.52.0 (302b608), recipe/mod.rs and validate_recipe.rs.

https://github.com/aaif-goose/goose/tree/v1.52.0/crates/goose/src/recipe
"""

from datetime import date
from typing import Optional

TOOL_DIR_NAME = ".goose"
RECIPE_SUFFIXES = frozenset({".yaml", ".yml", ".json"})
PROJECT_CONFIG_FILES = frozenset(
    {
        ".skillsaw.yaml",
        ".skillsaw.yml",
        ".claudelint.yaml",
        ".claudelint.yml",
        ".pre-commit-config.yaml",
        "mkdocs.yaml",
        "mkdocs.yml",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
    }
)
INPUT_TYPES = frozenset({"string", "number", "boolean", "date", "file", "select"})
REQUIREMENTS = frozenset({"required", "optional", "user_prompt"})
EXTENSION_TYPES = frozenset({"stdio", "builtin", "platform", "streamable_http"})


def recipe_string(value: object) -> Optional[str]:
    """serde_yaml accepts numeric and boolean scalars in string fields."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return None
