"""Warning categories for capabilities the linted repository turns on.

Raised when a repository's own configuration asks skillsaw to do
something the operator should be able to see happening — today, executing
a rule file out of the repository. The CLI renders it as one readable
line; a library caller gets an ordinary ``UserWarning`` subclass it can
filter.

It lives here rather than in :mod:`skillsaw.linter` because the CLI
installs its warning renderer before it has decided whether this
invocation lints anything, and reaching into the linter for a class
object would drag repository discovery and both YAML parsers along with
it. :mod:`skillsaw.linter` re-exports the name.
"""

from pathlib import Path


class CustomRuleWarning(UserWarning):
    """Emitted just before skillsaw executes a custom rule file from the repo.

    Carries ``path`` so the CLI can render the notice as a readable colored
    line instead of the stock ``warnings`` traceback format; library callers
    still get a normal ``UserWarning`` they can filter.
    """

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"Loading custom rule file: {path} — use --no-custom-rules to skip")
