"""Bounded matching for Pi resource globs and ignore files.

``pathspec`` and ``wcmatch`` are imported where they are used: discovery
imports this module on every run, and only a repository declaring Pi
resources ever matches a pattern.
"""

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Iterable, Sequence

from .timeouts import RegexTimeout, regex_timeout

if TYPE_CHECKING:
    from pathspec import GitIgnoreSpec

_PATTERN_SECONDS = 0.02
_MAX_PATTERN_LENGTH = 1024
_MAX_IGNORE_PATTERNS = 4096


@lru_cache(maxsize=256)
def _compile_glob(pattern: str):
    if not pattern or len(pattern) > _MAX_PATTERN_LENGTH:
        return None
    from wcmatch import glob

    with regex_timeout(_PATTERN_SECONDS):
        return glob.compile(pattern, flags=glob.GLOBSTAR | glob.BRACE | glob.EXTGLOB, limit=256)


def _globmatch(value: str, pattern: str) -> bool:
    try:
        compiled = _compile_glob(pattern)
        with regex_timeout(_PATTERN_SECONDS):
            return compiled.match(value) if compiled is not None else False
    except Exception:
        # wcmatch exposes expansion-limit exceptions through private modules.
        # Keep failures local to this pattern; failed compilations are not cached.
        return False


def _ignore_spec(patterns: Sequence = ()) -> "GitIgnoreSpec":
    from pathspec import GitIgnoreSpec

    return GitIgnoreSpec(list(patterns[-_MAX_IGNORE_PATTERNS:]), backend="simple")


def _ignore_patterns(lines: Iterable[str]) -> list:
    from pathspec import GitIgnoreSpec

    patterns = []
    for index, line in enumerate(lines):
        if index >= _MAX_IGNORE_PATTERNS:
            break
        if len(line) > _MAX_PATTERN_LENGTH:
            continue
        try:
            with regex_timeout(_PATTERN_SECONDS):
                patterns.extend(GitIgnoreSpec.from_lines([line], backend="simple").patterns)
        except (ValueError, re.error, RecursionError, RegexTimeout):
            # GitIgnorePatternError (including the legacy GitWildMatch spelling)
            # derives from ValueError. A bad line must not suppress valid siblings.
            continue
    return patterns


def _ignored(ignore: "GitIgnoreSpec", value: str) -> bool:
    try:
        with regex_timeout(_PATTERN_SECONDS):
            return ignore.match_file(value)
    except (ValueError, re.error, RecursionError, RegexTimeout):
        return False
