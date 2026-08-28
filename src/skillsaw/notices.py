"""Warning categories for capabilities the linted repository turns on.

Both are raised when a repository's own configuration asks skillsaw to do
something the operator should be able to see happening — execute a rule
file out of the repository, or make outbound requests. The CLI renders
them as one readable line each; a library caller gets ordinary
``UserWarning`` subclasses it can filter.

They live here rather than in :mod:`skillsaw.linter` because the CLI
installs its warning renderer before it has decided whether this
invocation lints anything, and reaching into the linter for two class
objects would drag repository discovery and both YAML parsers along with
them. :mod:`skillsaw.linter` re-exports both names.
"""

from pathlib import Path
from typing import List


class CustomRuleWarning(UserWarning):
    """Emitted just before skillsaw executes a custom rule file from the repo.

    Carries ``path`` so the CLI can render the notice as a readable colored
    line instead of the stock ``warnings`` traceback format; library callers
    still get a normal ``UserWarning`` they can filter.
    """

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"Loading custom rule file: {path} — use --no-custom-rules to skip")


class NetworkAccessWarning(UserWarning):
    """Emitted when a rule that makes outbound requests is about to run.

    The linted repository's own config decides whether such a rule is
    enabled, so the operator has to be able to see that it happened —
    the same reason ``CustomRuleWarning`` exists for the other
    repo-config-activated capability.
    """

    def __init__(self, rule_ids: List[str]):
        self.rule_ids = rule_ids
        super().__init__(
            f"Network access enabled for: {', '.join(rule_ids)} — use --no-network to skip"
        )
