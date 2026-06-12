"""Synthetic repository generator for benchmarking.

Generates a deterministic, realistic marketplace repository (plugins with
commands/agents/hooks, skills with references, instruction files, settings)
at a configurable scale.  The same scale always produces byte-identical
output so benchmark runs are comparable across invocations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

SCALES: Dict[str, Dict[str, int]] = {
    "tiny": dict(plugins=1, commands=2, agents=1, skills=2, refs=1),
    "small": dict(plugins=5, commands=5, agents=2, skills=10, refs=2),
    "medium": dict(plugins=20, commands=10, agents=4, skills=50, refs=3),
    "large": dict(plugins=60, commands=12, agents=6, skills=200, refs=3),
}

_WORDS = (
    "configure validate inspect resolve merge format detect report "
    "the repository each plugin every skill a command this agent "
    "before linting after parsing during discovery without errors "
    "frontmatter heading metadata description structure content rules"
).split()


def _sentence(seed: int, length: int = 9) -> str:
    words = [_WORDS[(seed * 7 + i * 3) % len(_WORDS)] for i in range(length)]
    return words[0].capitalize() + " " + " ".join(words[1:]) + "."


def _paragraph(seed: int, sentences: int = 4) -> str:
    return " ".join(_sentence(seed + i) for i in range(sentences))


def _prose_body(seed: int, sections: int = 3) -> str:
    parts = []
    for s in range(sections):
        parts.append(f"## Section {s + 1}\n")
        parts.append(_paragraph(seed + s * 10) + "\n")
        parts.append(
            "```bash\n"
            f"tool run --target item-{seed % 50} --verbose\n"
            "```\n"
        )
        parts.append(
            f"See [the reference](https://example.com/docs/{seed % 20}) "
            f"and run `tool check` before committing.\n"
        )
    return "\n".join(parts)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _command_md(plugin: str, idx: int) -> str:
    return f"""---
description: Run task {idx} for {plugin} with validation and reporting
---

## Name
{plugin}:task-{idx}

## Synopsis
```
/{plugin}:task-{idx} [target]
```

## Description
{_paragraph(idx * 3 + 1)}

## Implementation
1. Inspect the target and gather metadata.
2. Validate the configuration against the schema.
3. Report results with `tool report --format json`.

{_prose_body(idx * 5 + 2, sections=2)}
"""


def _agent_md(plugin: str, idx: int) -> str:
    return f"""---
name: {plugin}-agent-{idx}
description: Use this agent to handle workflow {idx} for {plugin}, including validation and reporting steps
---

You are a focused assistant for workflow {idx} in {plugin}.

{_prose_body(idx * 11 + 3, sections=2)}
"""


def _skill_md(name: str, idx: int) -> str:
    return f"""---
name: {name}
description: Use this skill when you need to perform workflow {idx}, validate the structure, and report results
---

# {name}

{_paragraph(idx * 13 + 5)}

## Instructions

1. Read the input files carefully.
2. Validate the structure with `tool validate`.
3. Report results in the requested format.

{_prose_body(idx * 17 + 7, sections=3)}
"""


def _reference_md(skill: str, idx: int) -> str:
    return f"""# Reference {idx} for {skill}

{_prose_body(idx * 19 + 11, sections=4)}
"""


def _claude_md() -> str:
    return f"""# Project Standards

This repository contains plugins and skills used by automated agents.

{_prose_body(101, sections=4)}

## Development

- Run `make test` before pushing changes.
- Keep documentation in sync with behavior.

{_prose_body(202, sections=3)}
"""


def generate_repo(root: Path, scale: str = "medium") -> Dict[str, int]:
    """Generate a synthetic repository at *root*. Returns file/entity counts."""
    params = SCALES[scale]
    root.mkdir(parents=True, exist_ok=True)

    plugin_names = [f"plugin-{i:03d}" for i in range(params["plugins"])]

    marketplace = {
        "name": "bench-marketplace",
        "owner": {"name": "Bench Owner", "email": "bench@example.com"},
        "plugins": [
            {
                "name": name,
                "source": f"./plugins/{name}",
                "description": f"Benchmark plugin {name} for performance testing",
            }
            for name in plugin_names
        ],
    }
    _write(
        root / ".claude-plugin" / "marketplace.json",
        json.dumps(marketplace, indent=2) + "\n",
    )

    files = 1
    for p_idx, name in enumerate(plugin_names):
        pdir = root / "plugins" / name
        _write(
            pdir / ".claude-plugin" / "plugin.json",
            json.dumps(
                {
                    "name": name,
                    "description": f"Benchmark plugin {name} for performance testing",
                    "version": "1.0.0",
                    "author": {"name": "Bench Owner"},
                },
                indent=2,
            )
            + "\n",
        )
        _write(pdir / "README.md", f"# {name}\n\n{_paragraph(p_idx)}\n")
        files += 2
        for c in range(params["commands"]):
            _write(pdir / "commands" / f"task-{c}.md", _command_md(name, c))
            files += 1
        for a in range(params["agents"]):
            _write(pdir / "agents" / f"agent-{a}.md", _agent_md(name, a))
            files += 1
        if p_idx % 3 == 0:
            _write(
                pdir / "hooks" / "hooks.json",
                json.dumps(
                    {
                        "hooks": {
                            "PostToolUse": [
                                {
                                    "matcher": "Write|Edit",
                                    "hooks": [
                                        {"type": "command", "command": "make lint"}
                                    ],
                                }
                            ]
                        }
                    },
                    indent=2,
                )
                + "\n",
            )
            files += 1

    skills_root = root / "skills"
    for s_idx in range(params["skills"]):
        sname = f"skill-{s_idx:04d}"
        sdir = skills_root / sname
        _write(sdir / "SKILL.md", _skill_md(sname, s_idx))
        files += 1
        for r in range(params["refs"]):
            _write(sdir / "references" / f"ref-{r}.md", _reference_md(sname, r))
            files += 1

    _write(root / "CLAUDE.md", _claude_md())
    _write(root / "AGENTS.md", _claude_md())
    _write(
        root / ".claude" / "settings.json",
        json.dumps(
            {"permissions": {"allow": ["Bash(make test)", "Bash(make lint)"]}},
            indent=2,
        )
        + "\n",
    )
    files += 3

    return {
        "files": files,
        "plugins": params["plugins"],
        "skills": params["skills"],
        "scale_params": dict(params),  # type: ignore[dict-item]
    }
