"""
Shared helpers for APM rules
"""

from typing import Optional

from skillsaw.rules.builtin.utils import read_text, yaml_key_line


def _yaml_key_line(file_path, key: str) -> Optional[int]:
    """Find the line number of a top-level key in a YAML file.

    Uses ruamel.yaml round-trip parsing for accurate line tracking.
    """
    content = read_text(file_path)
    if content is None:
        return None
    return yaml_key_line(content, key, top_level=True)
