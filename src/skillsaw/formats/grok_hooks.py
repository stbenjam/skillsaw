"""The numeric token distinction in Grok's JSON hook reader."""

import json
from pathlib import Path
from typing import Any, Optional, Tuple

from skillsaw.utils import read_text


def read_hooks_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Preserve negative zero as a float, as serde_json::Value does.

    The unsigned timeout validator must distinguish literal -0 from 0.
    Duplicate keys and non-finite tokens retain the existing lenient policy
    so authored commands remain available to shared hook inspections.
    """
    content = read_text(path)
    if content is None:
        return None, f"Failed to read {path.name}"
    try:
        return (
            json.loads(content, parse_int=lambda token: -0.0 if token == "-0" else int(token)),
            None,
        )
    except ValueError as error:
        return None, str(error)
    except RecursionError:
        return None, "Nesting too deep to parse"
