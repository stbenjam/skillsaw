"""Left over from an earlier version of the skill; nothing references it."""

import shutil


def wipe(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)
