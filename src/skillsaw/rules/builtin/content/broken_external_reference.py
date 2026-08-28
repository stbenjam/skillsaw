"""Content broken external reference rule.

The only rule in skillsaw that opens a network connection.  Everything
here is built around two constraints that follow from that:

* It is **opt-in** (``default_enabled = False``).  A lint run must be
  hermetic unless the user asked for otherwise, so a default run never
  constructs an opener, let alone a socket.
* It reports **only definitive evidence** — HTTP 404 and 410.  A bot
  wall (403), a rate limit (429), a flaky origin (5xx), a timeout, a
  DNS failure, or a TLS error says something about the network between
  the runner and the host, not about the link.  Failing CI on those
  would make the rule worse than no rule at all.
"""

import fnmatch
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks

# The only statuses that mean "this link is dead" rather than "the
# network said something about the runner". Kept as a mapping so the
# message names the status the way a reader will see it in a browser.
_BROKEN_STATUSES = {
    404: "404 Not Found",
    410: "410 Gone",
}

# Servers that reject HEAD outright. One GET retry (headers only, body
# never read) settles those without turning every probe into a download.
_RETRY_WITH_GET = frozenset({405, 501})

# A HEAD answer is never enough to convict. RFC 9110 says HEAD must
# return what GET would minus the body, and plenty of servers simply do
# not: nvlpubs.nist.gov answers 404 to HEAD and serves the PDF on GET,
# and azure.microsoft.com does the same on some marketing paths. Both
# showed up as false positives in the first real-repo run of this rule.
# So a candidate violation is always re-asked with GET, and GET's answer
# is the one that counts. The extra request is paid only for links that
# are about to be reported, which is a small minority of any repository.
_CONFIRM_WITH_GET = frozenset(_BROKEN_STATUSES)

# Same rationale as the sibling internal-reference rule: files under a
# template directory carry placeholder targets on purpose.
_TEMPLATE_DIR_NAMES = frozenset({"template", "templates", "_template"})

# Glob metacharacters. A pattern without any of them is a plain prefix.
_GLOB_CHARS = ("*", "?", "[")

# Redirect chains are followed, but not indefinitely.
_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class _Occurrence:
    """One link in one file, pointing at one external URL."""

    block: Any  # ContentBlock; typed loosely to keep this leaf rule import-light
    body_line: int
    text: str
    href: str


class _BoundedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler with a tighter hop cap and an http(s)-only target.

    ``urllib`` allows a redirect into ``ftp://`` by default. The rule
    only ever speaks http(s) — a URL scheme is the one thing keeping a
    repository-authored string from reaching a non-HTTP client — so a
    redirect out of those schemes ends the chain the same way urllib
    ends a redirect into any other scheme: as an HTTPError, which the
    caller reads as inconclusive.
    """

    max_redirections = _MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme not in ("http", "https"):
            raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ContentBrokenExternalReferenceRule(Rule):
    """Detect external links whose server definitively reports them gone"""

    # Opt-in, always: a lint run is hermetic unless the user says
    # otherwise. Never "auto" — no repo type or detected format may
    # start making network requests on a user's behalf.
    default_enabled = False

    formats = None
    since = "0.20.0"
    repo_types = None

    config_schema = {
        "timeout": {
            "type": "float",
            "default": 5.0,
            "description": "Per-request timeout in seconds",
        },
        "total-budget": {
            "type": "float",
            "default": 30.0,
            "description": (
                "Wall-clock seconds for all requests in a run; "
                "remaining URLs are left unchecked. 0 disables the cap"
            ),
        },
        "concurrency": {
            "type": "int",
            "default": 8,
            "description": "Maximum simultaneous requests",
        },
        "ignore": {
            "type": "list",
            "default": [],
            "description": (
                "URL patterns never requested — a glob (fnmatch) when it "
                "contains *, ? or [, otherwise a literal prefix"
            ),
        },
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        # Openers are per-thread (see _opener). The holder is created here,
        # before any worker exists, so no two threads race to create it.
        self._local = threading.local()

    @property
    def rule_id(self) -> str:
        return "content-broken-external-reference"

    @property
    def description(self) -> str:
        return "Detect external http(s) links whose server reports them gone (404/410)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    # -- collection ---------------------------------------------------------

    @staticmethod
    def _is_in_template_dir(path: Path) -> bool:
        return any(part in _TEMPLATE_DIR_NAMES for part in path.parts)

    @staticmethod
    def _request_url(href: str) -> Optional[str]:
        """The URL to request for *href*, or None when it is out of scope.

        Only ``http``/``https`` are probed. A fragment is dropped — it is
        never sent to the server, and keeping it would split one request
        into several. A URL carrying userinfo is dropped entirely rather
        than probed: the request would put the author's credentials on
        the wire, which is not something a linter should do on its own.
        """
        try:
            parts = urlsplit(href)
        except ValueError:
            return None
        if parts.scheme not in ("http", "https"):
            return None
        if not parts.netloc:
            return None
        if "@" in parts.netloc:
            return None
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))

    @staticmethod
    def _is_ignored(url: str, patterns: Sequence[str]) -> bool:
        for pattern in patterns:
            if not isinstance(pattern, str) or not pattern:
                continue
            if any(char in pattern for char in _GLOB_CHARS):
                if fnmatch.fnmatchcase(url, pattern):
                    return True
            elif url.startswith(pattern):
                return True
        return False

    def _collect(self, context: RepositoryContext) -> Dict[str, List[_Occurrence]]:
        """Map request URL -> every occurrence of it across the repository.

        De-duplication happens here, before any I/O: a URL repeated in
        forty skills costs one request, and each occurrence still gets
        its own violation with its own line.
        """
        ignore = [p for p in self.setting("ignore") if isinstance(p, str)]
        by_url: Dict[str, List[_Occurrence]] = {}
        for block in gather_all_content_blocks(context):
            if self._is_in_template_dir(block.path):
                continue
            # Links come from the markdown AST, so fenced and indented
            # code blocks contribute nothing and autolinks contribute
            # exactly like inline links.
            for link in block.markdown.links():
                href = link.href.strip()
                url = self._request_url(href)
                if url is None or self._is_ignored(url, ignore):
                    continue
                by_url.setdefault(url, []).append(
                    _Occurrence(
                        block=block,
                        body_line=link.body_line,
                        text=link.text,
                        href=href,
                    )
                )
        return by_url

    # -- network ------------------------------------------------------------

    @staticmethod
    def _user_agent() -> str:
        from skillsaw import __version__

        return f"skillsaw/{__version__} (+https://skillsaw.org)"

    def _opener(self) -> urllib.request.OpenerDirector:
        """A per-thread opener.

        ``build_opener`` reads the proxy environment, so it is built once
        per worker thread rather than once per URL, and never shared
        across threads.
        """
        opener = getattr(self._local, "opener", None)
        if opener is None:
            opener = urllib.request.build_opener(_BoundedRedirectHandler)
            opener.addheaders = []
            self._local.opener = opener
        return opener

    def _request(self, url: str, method: str, timeout: float) -> Optional[int]:
        """Status code for one request, or None when nothing was learned.

        The response body is never read: the context manager closes the
        connection as soon as the status line and headers have arrived.
        """
        request = urllib.request.Request(
            url,
            method=method,
            headers={"User-Agent": self._user_agent(), "Accept": "*/*"},
        )
        try:
            with self._opener().open(request, timeout=timeout) as response:
                return getattr(response, "status", None)
        except urllib.error.HTTPError as exc:
            code = exc.code
            try:
                exc.close()
            except Exception:
                pass
            return code
        except Exception:
            # Timeouts, DNS failures, refused connections, TLS errors,
            # malformed responses, redirect loops. Every one of them is
            # a statement about the network, not about the link.
            return None

    def _probe(
        self, url: str, timeout: float, deadline: Optional[float]
    ) -> Tuple[Optional[int], bool]:
        """``(status, checked)`` for *url*, honouring the run-wide deadline."""
        request_timeout = timeout
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, False
            request_timeout = min(timeout, remaining)
        status = self._request(url, "HEAD", request_timeout)
        # Ask again with GET for two different reasons: the server
        # refuses HEAD (405/501), or the HEAD answer would convict the
        # link (404/410) and a HEAD-only answer is not evidence. Either
        # way GET is authoritative — including when it answers nothing
        # at all, which leaves the link unreported.
        if status in _RETRY_WITH_GET or status in _CONFIRM_WITH_GET:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Out of budget mid-confirmation. The unconfirmed
                    # HEAD status is discarded rather than reported:
                    # when in doubt, stay silent.
                    return None, True
                request_timeout = min(timeout, remaining)
            status = self._request(url, "GET", request_timeout)
        return status, True

    def _probe_all(
        self, urls: List[str], timeout: float, budget: float, concurrency: int
    ) -> Tuple[Dict[str, Optional[int]], int]:
        """Probe every URL, returning ``(statuses, unchecked_count)``.

        A URL still queued when the budget runs out is never requested,
        and a request already in flight is bounded by whatever is left of
        the budget — so the run's network time stays close to the cap
        however many links the repository has.
        """
        workers = max(1, min(concurrency, len(urls)))
        deadline = time.monotonic() + budget if budget > 0 else None

        statuses: Dict[str, Optional[int]] = {}
        unchecked = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._probe, url, timeout, deadline): url for url in urls}
            for future, url in futures.items():
                try:
                    status, checked = future.result()
                except Exception:
                    status, checked = None, True
                if checked:
                    statuses[url] = status
                else:
                    unchecked += 1
        return statuses, unchecked

    # -- check --------------------------------------------------------------

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        by_url = self._collect(context)
        if not by_url:
            return []

        timeout = max(0.1, _as_float(self.setting("timeout"), 5.0))
        budget = _as_float(self.setting("total-budget"), 30.0)
        concurrency = _as_int(self.setting("concurrency"), 8)

        # Sorted so a run's request order — and therefore which URLs a
        # short budget reaches — is deterministic for the same repository.
        statuses, unchecked = self._probe_all(sorted(by_url), timeout, budget, concurrency)

        violations: List[RuleViolation] = []
        for url in sorted(by_url):
            reason = _BROKEN_STATUSES.get(statuses.get(url))
            if reason is None:
                continue
            for occurrence in by_url[url]:
                violations.append(
                    self.violation(
                        f"Broken external link: [{safe_display(occurrence.text)}]"
                        f"({safe_display(occurrence.href)}) — server returned {reason}",
                        block=occurrence.block,
                        line=occurrence.body_line,
                        fixable=False,
                    )
                )
        if unchecked:
            # One notice per run, never one per URL: an exhausted budget
            # is a property of the run, and repeating it per link would
            # bury the findings it was protecting. Info severity — an
            # incomplete check is not a finding about the repository.
            violations.append(
                self.violation(
                    f"{unchecked} external URL(s) unchecked "
                    f"(network budget of {budget:g}s exhausted)",
                    severity=Severity.INFO,
                    fixable=False,
                )
            )
        return violations


def _as_float(value: Any, fallback: float) -> float:
    """A configured number, or *fallback* when it is not one.

    Config validation warns about a wrong-typed option but still hands
    the value through, so a settings read must not be able to raise out
    of ``check()``.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
