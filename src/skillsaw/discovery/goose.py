"""State-free discovery and local reference resolution for Goose recipes."""

from pathlib import Path
from typing import Callable, Iterable, Optional

from skillsaw.formats.goose import RECIPE_SUFFIXES
from skillsaw.paths import contained_resolve, is_absolute_path, safe_is_file


def recipe_files(directory: Path) -> Iterable[Path]:
    """Enumerate a declared recipe directory, never arbitrary repository YAML."""
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if path.suffix in RECIPE_SUFFIXES:
            yield path


def local_subrecipe(
    value: str, recipe: Path, workspace: Path, root: Path, resolve: Callable
) -> Optional[Path]:
    """Resolve literal paths inside the lint root; leave external names alone.

    Goose resolves file paths from the working directory. ``recipe_dir`` is
    its built-in template variable for paths relative to the recipe itself.
    Library names, remote sources and other templates require runtime state.
    """
    for prefix in ("{{ recipe_dir }}/", "{{recipe_dir}}/"):
        if value.startswith(prefix):
            candidate = recipe.parent / value[len(prefix) :]
            break
    else:
        if (
            "{{" in value
            or "{%" in value
            or "://" in value
            or value.startswith("~")
            or is_absolute_path(value)
            or Path(value).suffix not in {".yaml", ".json"}
        ):
            return None
        candidate = workspace / value
    return contained_resolve(candidate, root, resolve)


def existing_subrecipe(path: Optional[Path]) -> bool:
    return path is not None and safe_is_file(path)
