"""Inputs and byte accounting for Codex 0.162.1 project instructions.

See core/src/agents_md.rs and core/src/config/mod.rs at rust-v0.162.1.
This models one trusted local environment with an explicitly supplied root.
"""

from __future__ import annotations

import codecs
import os
from dataclasses import asdict, dataclass
from typing import Iterable, Optional, Tuple

DEFAULT_MAX_BYTES = 32 * 1024
# Codex's TOML value parser accepts signed 64-bit integers.
TOML_INTEGER_MIN = -(2**63)
TOML_INTEGER_MAX = 2**63 - 1
STANDARD_FILENAMES = ("AGENTS.override.md", "AGENTS.md")
# Rust str::trim uses Unicode White_Space; Python also strips U+001C..U+001F.
RUST_WHITESPACE = "\t\n\v\f\r \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def contains_out_of_range_integer(value: object) -> bool:
    """Find integers Python's TOML parser accepts but Codex's rejects."""
    pending = [iter((value,))]
    while pending:
        for item in pending[-1]:
            if type(item) is int and not TOML_INTEGER_MIN <= item <= TOML_INTEGER_MAX:
                return True
            if isinstance(item, (dict, list)):
                pending.append(iter(item.values() if isinstance(item, dict) else item))
                break
        else:
            pending.pop()
    return False


@dataclass(frozen=True)
class CodexInstructionOptions:
    """Explicit analysis inputs, not a claim about the user's Codex config."""

    cwd: str = "."
    project_doc_max_bytes: Optional[int] = None
    project_doc_fallback_filenames: Optional[Tuple[str, ...]] = None

    @classmethod
    def from_mapping(cls, value: object) -> "CodexInstructionOptions":
        if not isinstance(value, dict):
            raise ValueError("'codex-instructions' must be a mapping")
        unknown = value.keys() - cls.__dataclass_fields__.keys()
        if unknown:
            raise ValueError(
                f"Unknown codex-instructions option(s): {', '.join(sorted(map(str, unknown)))}"
            )
        cwd = value.get("cwd")
        if cwd is None:
            cwd = "."
        if not isinstance(cwd, str) or not cwd or "\0" in cwd:
            raise ValueError("codex-instructions.cwd must be a non-empty directory path")
        limit = value.get("project_doc_max_bytes")
        if limit is not None and (type(limit) is not int or not 0 <= limit <= TOML_INTEGER_MAX):
            raise ValueError(
                "codex-instructions.project_doc_max_bytes must be a non-negative integer "
                f"at most {TOML_INTEGER_MAX}"
            )
        names = value.get("project_doc_fallback_filenames")
        if names is not None and (
            not isinstance(names, list) or not all(isinstance(name, str) for name in names)
        ):
            raise ValueError(
                "codex-instructions.project_doc_fallback_filenames must be a list of strings"
            )
        return cls(cwd, limit, tuple(names) if names is not None else None)

    def to_dict(self) -> dict:
        values = asdict(self)
        if self.project_doc_fallback_filenames is not None:
            values["project_doc_fallback_filenames"] = list(self.project_doc_fallback_filenames)
        return {key: value for key, value in values.items() if value is not None}


def candidate_filenames(fallbacks: Tuple[str, ...]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Normalize like Config, then reject path syntax before any probes."""
    names = list(STANDARD_FILENAMES)
    ignored = []
    for raw in fallbacks:
        name = raw.strip(RUST_WHITESPACE)
        if not name:
            continue
        if (
            name in {".", ".."}
            or "/" in name
            or "\0" in name
            or (os.name == "nt" and ("\\" in name or ":" in name))
        ):
            ignored.append(raw)
        elif name not in names:
            names.append(name)
    return tuple(names), tuple(ignored)


@dataclass(frozen=True)
class InstructionBytes:
    file_bytes: int
    read_bytes: int
    charged_bytes: int
    text_bytes: int
    status: str
    truncated: bool


def instruction_bytes(
    chunks: Iterable[bytes], remaining: int, *, file_bytes: int
) -> InstructionBytes:
    """Account for a raw prefix without retaining it or splitting UTF-8 decoding."""
    if remaining == 0:
        return InstructionBytes(file_bytes, 0, 0, 0, "omitted", False)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    read_bytes = text_bytes = 0
    has_text = False
    for chunk in chunks:
        prefix = chunk[: remaining - read_bytes]
        read_bytes += len(prefix)
        text = decoder.decode(prefix)
        text_bytes += len(text.encode("utf-8"))
        has_text = has_text or bool(text.strip(RUST_WHITESPACE))
        if read_bytes == remaining:
            break
    # A budget boundary or EOF can leave an incomplete UTF-8 sequence.
    tail = decoder.decode(b"", final=True)
    text_bytes += len(tail.encode("utf-8"))
    has_text = has_text or bool(tail.strip(RUST_WHITESPACE))
    truncated = read_bytes < file_bytes
    if not has_text:
        return InstructionBytes(file_bytes, read_bytes, 0, 0, "empty", truncated)
    return InstructionBytes(
        file_bytes,
        read_bytes,
        read_bytes,
        text_bytes,
        "truncated" if truncated else "loaded",
        truncated,
    )
