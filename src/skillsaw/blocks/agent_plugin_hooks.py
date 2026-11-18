"""The flat command arrays in portable Agent Plugins hooks.json."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from skillsaw.blocks.json_config import HookEventConfig, HookHandler, HooksBlock


@dataclass(eq=False)
class AgentPluginHooksBlock(HooksBlock):
    strict_json: ClassVar[bool] = True

    @property
    def events(self) -> dict[str, list[HookEventConfig]]:
        """Expose declared executables and arguments to the shared hook rules."""
        hooks = (self.raw_data or {}).get("hooks")
        if not isinstance(hooks, dict):
            return {}
        events = {}
        for event, entries in hooks.items():
            if not isinstance(entries, list):
                continue
            handlers = []
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
                    continue
                args = entry.get("args", [])
                if isinstance(args, list) and all(isinstance(arg, str) for arg in args):
                    handlers.append(
                        HookHandler(type="command", command=entry["command"], args=args)
                    )
            if handlers:
                events[event] = [HookEventConfig(handlers=handlers)]
        return events
