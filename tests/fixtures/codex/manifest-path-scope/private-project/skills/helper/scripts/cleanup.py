"""Remove stale artifacts from the working tree."""

import pathlib

for stale in pathlib.Path(".").glob("**/*.tmp"):
    stale.unlink()
