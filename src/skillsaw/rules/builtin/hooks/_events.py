"""Shared-file handling for the hook security rules."""

from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Set, Tuple

from skillsaw.blocks.json_config import HookEventConfig, HooksBlock
from skillsaw.paths import safe_resolve


def unique_hook_events(
    blocks: Iterable[HooksBlock],
) -> Iterator[Tuple[Path, Dict[str, List[HookEventConfig]]]]:
    """Scan each host's reading, omitting handlers a previous reading exposed.

    Deduplicate across blocks of the same resolved file only. Repeated
    handlers within one block retain their existing findings, and a host
    that recognizes extra handlers still contributes them.
    """
    seen_by_path: Dict[Path, Set[Tuple[object, ...]]] = {}
    for block in blocks:
        if block.parse_error:
            continue
        path = safe_resolve(block.path) or block.path
        seen = seen_by_path.setdefault(path, set())
        current = set()
        events = {}
        for event, configs in block.security_events.items():
            filtered = []
            for config in configs:
                handlers = []
                for handler in config.handlers:
                    identity = (
                        event.casefold(),
                        handler.type,
                        tuple(handler.iter_effective_commands()),
                        handler.url,
                        handler.server,
                        handler.tool,
                        handler.prompt,
                    )
                    if identity not in seen:
                        handlers.append(handler)
                    current.add(identity)
                if handlers:
                    filtered.append(HookEventConfig(matcher=config.matcher, handlers=handlers))
            if filtered:
                events[event] = filtered
        seen.update(current)
        yield block.path, events
