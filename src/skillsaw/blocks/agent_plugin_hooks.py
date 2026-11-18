"""The flat command arrays in portable Agent Plugins hooks.json."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from skillsaw.blocks.json_config import HookEventConfig, HookHandler, HooksBlock


@dataclass(eq=False)
class AgentPluginHooksBlock(HooksBlock):
    """An Agent Plugins 1.1.0 package's root ``hooks.json``.

    The portable shape is flat: ``{$schema, hooks: {Event: [{command, args?,
    extensions?}]}}``, with no matcher or handler ``type``. :attr:`events`
    renders it for the shared hook rules; ``agent-plugin-hooks-valid``
    checks the shape.
    """

    strict_json: ClassVar[bool] = True

    def tree_label(self) -> str:
        return f"{self.path.name} (agent plugin hooks)"

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
                # Malformed args must not hide the executable from the
                # security rules; keep the command and its string arguments.
                args = entry.get("args")
                args = (
                    [arg for arg in args if isinstance(arg, str)] if isinstance(args, list) else []
                )
                handlers.append(HookHandler(type="command", command=entry["command"], args=args))
            if handlers:
                events[event] = [HookEventConfig(handlers=handlers)]
        return events
