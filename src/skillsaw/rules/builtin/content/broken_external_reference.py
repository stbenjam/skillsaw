"""Content broken external reference rule.

The only rule in skillsaw that opens a network connection.  Everything
here is built around three constraints that follow from that:

* It is **opt-in** (``default_enabled = False``), and the operator can
  refuse regardless of what the linted repository's config says — see
  ``requires_network`` and ``--no-network``.  A default run never
  constructs an opener, let alone a socket.
* It reports **only definitive evidence** — HTTP 404 and 410.  A bot
  wall (403), a rate limit (429), a flaky origin (5xx), a timeout, a
  DNS failure, or a TLS error says something about the network between
  the runner and the host, not about the link.
* Every input it acts on comes from an untrusted repository: the URLs
  from its content files and the tuning options from its
  ``.skillsaw.yaml``.  So destinations are confined to public hosts by
  default, and every option is clamped rather than trusted.
"""

import fnmatch
import ipaddress
import logging
import math
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks

logger = logging.getLogger(__name__)

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

_MAX_REDIRECTS = 5

# Upper bounds on the tuning options, in the style of
# ``_MAX_REGEX_TIMEOUT`` in the banned-references rule (T13). Every one
# of these arrives from a ``.skillsaw.yaml`` that the threat model
# classifies as untrusted repository content, so "the user asked for it"
# is not a reason to honour a value that hangs CI or exhausts a runner.
# A worker's worst case is _MAX_REDIRECTS x timeout, so the clamped
# timeout is what actually bounds the run.
_MAX_TIMEOUT = 30.0
_MAX_TOTAL_BUDGET = 600.0
_MAX_CONCURRENCY = 32

# Hostnames that are never public, whatever DNS says.
_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

# Exceptions a probe is allowed to swallow: every way the network can
# fail to answer. Anything outside this set is a bug in the rule, and a
# bug must surface as a rule-execution-error rather than as a quiet
# "nothing to report" — see linter.Linter.run's crash contract.
# OSError already covers URLError, SSLError, timeout, gaierror and the
# connection errors; they are named for the reader, not for coverage.
# Deliberately NOT here: bare ValueError, TypeError, AttributeError.
# http.client.InvalidURL is an HTTPException, so a malformed URL is
# still caught, but a plain ValueError is far likelier to be a bug in
# this rule than a network condition.
_NETWORK_ERRORS = (
    urllib.error.URLError,
    HTTPException,
    ssl.SSLError,
    socket.timeout,
    socket.gaierror,
    OSError,
    UnicodeError,  # IDNA encoding of a hostile hostname
)


@dataclass(frozen=True)
class _Occurrence:
    """One link in one file, pointing at one external URL."""

    block: Any  # ContentBlock; typed loosely to keep this leaf rule import-light
    body_line: int
    text: str
    href: str


class _BoundedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler with a tighter hop cap and a vetted target.

    Every admission rule that applies to an authored URL applies again
    to each hop, because the destination past the first hop is chosen by
    the origin rather than by the repository author. Without that,
    ``ignore`` — the mechanism the docs tell users to keep skillsaw off
    their internal network — is bypassable by any origin willing to
    answer 302, and so is the private-host confinement. urllib would
    also happily follow a redirect into ``ftp://`` or re-send userinfo
    credentials on the next hop.

    A rejected hop ends the chain the way urllib ends a redirect into an
    unsupported scheme: as an ``HTTPError``, which the caller reads as
    inconclusive.
    """

    max_redirections = _MAX_REDIRECTS

    def __init__(self, accepts):
        self._accepts = accepts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self._accepts(newurl):
            raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ContentBrokenExternalReferenceRule(Rule):
    """Detect external links whose server definitively reports them gone"""

    # Opt-in, always: a lint run is hermetic unless the user says
    # otherwise. Never "auto" — no repo type or detected format may
    # start making network requests on a user's behalf.
    default_enabled = False

    # The operator's gate. The linted repository's own config decides
    # whether this rule is *enabled*; ``--no-network`` /
    # SKILLSAW_NO_NETWORK decides whether it may run at all, and the
    # repository cannot override that. Declarative on purpose: the
    # linter reads the attribute, so the next network rule inherits the
    # gate instead of a rule-id list needing maintenance.
    requires_network = True

    formats = None
    since = "0.20.0"
    repo_types = None

    config_schema = {
        "timeout": {
            "type": "float",
            "default": 5.0,
            "description": f"Per-request timeout in seconds (clamped to {_MAX_TIMEOUT:g})",
        },
        "total-budget": {
            "type": "float",
            "default": 30.0,
            "description": (
                "Wall-clock seconds for all requests in a run; remaining URLs "
                f"are left unchecked. 0 disables the cap (clamped to {_MAX_TOTAL_BUDGET:g})"
            ),
        },
        "concurrency": {
            "type": "int",
            "default": 8,
            "description": f"Maximum simultaneous requests (clamped to {_MAX_CONCURRENCY})",
        },
        "ignore": {
            "type": "list",
            "default": [],
            "description": (
                "URL patterns never requested — a glob (fnmatch) when it "
                "contains *, ? or [, otherwise a literal prefix"
            ),
        },
        "allow-private-hosts": {
            "type": "bool",
            "default": False,
            "description": (
                "Probe URLs whose host is a loopback, private, link-local or "
                "otherwise non-public IP literal. Off by default so a repo "
                "cannot aim the linter at its runner's internal network"
            ),
        },
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        # Openers are per-thread (see _opener). The holder is created here,
        # before any worker exists, so no two threads race to create it.
        self._local = threading.local()
        # Admission policy, resolved once from config. The redirect
        # handler consults it from worker threads, so it must be settled
        # before any request starts — and settling it in the constructor
        # means a direct _probe() call is governed by it too, not only a
        # call that came through check().
        self._ignore = [p for p in _as_list(self.setting("ignore"), []) if isinstance(p, str)]
        self._allow_private = self.setting("allow-private-hosts") is True

    @property
    def rule_id(self) -> str:
        return "content-broken-external-reference"

    @property
    def description(self) -> str:
        return (
            "Detect external http(s) links whose server reports them gone "
            "(404/410; opt-in, makes network requests)"
        )

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
    def _is_public_host(netloc: str) -> bool:
        """False when *netloc*'s host is knowably not on the public internet.

        Only IP literals and the reserved local names can be settled
        without a resolver, and this deliberately does not resolve: a
        lookup here would be a network call made before the network gate
        is honoured, and its answer would be stale by the time urllib
        connects anyway (DNS rebinding). So an internal *name* still gets
        through — the honest limits are documented on the rule page, and
        ``--no-network`` is the control that does not depend on parsing.
        """
        host = netloc.rsplit("@", 1)[-1]
        if host.startswith("["):
            host = host.partition("]")[0][1:]
        elif ":" in host:
            host = host.rsplit(":", 1)[0]
        host = host.strip().rstrip(".").lower()
        if not host:
            return False
        if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # A name. Not resolvable to a verdict here; see the docstring.
            return True
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            address = mapped
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        )

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

    def _admit(self, href: str) -> Optional[str]:
        """The URL to request for *href*, or None if it is not allowed.

        The single admission gate, applied both to authored URLs and to
        every redirect hop — see :class:`_BoundedRedirectHandler`.
        """
        url = self._request_url(href)
        if url is None:
            return None
        if not self._allow_private and not self._is_public_host(urlsplit(url).netloc):
            return None
        if self._is_ignored(url, self._ignore):
            return None
        return url

    def _accepts_hop(self, newurl: str) -> bool:
        """Whether a redirect target passes the same gate as an authored URL."""
        return self._admit(newurl) is not None

    def _collect(self, context: RepositoryContext) -> Dict[str, List[_Occurrence]]:
        """Map request URL -> every occurrence of it across the repository.

        De-duplication happens here, before any I/O: a URL repeated in
        forty skills costs one request, and each occurrence still gets
        its own violation with its own line.
        """
        by_url: Dict[str, List[_Occurrence]] = {}
        for block in gather_all_content_blocks(context):
            if self._is_in_template_dir(block.path):
                continue
            # Links come from the markdown AST, so fenced and indented
            # code blocks contribute nothing and autolinks contribute
            # exactly like inline links.
            for link in block.markdown.links():
                href = link.href.strip()
                url = self._admit(href)
                if url is None:
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
            opener = urllib.request.build_opener(_BoundedRedirectHandler(self._accepts_hop))
            opener.addheaders = []
            self._local.opener = opener
        return opener

    def _request(self, url: str, method: str, timeout: float) -> Optional[int]:
        """Status code for one request, or None when nothing was learned.

        The response body is never read: the context manager closes the
        connection as soon as the status line and headers have arrived.

        Only network failures are swallowed. A ``TypeError`` or an
        ``AttributeError`` from a bug in this rule propagates, so the
        linter turns it into an unbaselinable ``rule-execution-error``
        instead of the rule quietly reporting nothing and the run
        exiting 0 looking healthy.
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
            except OSError:
                pass
            return code
        except _NETWORK_ERRORS:
            # Timeouts, DNS failures, refused connections, TLS errors,
            # malformed responses, redirect loops, rejected hops. Every
            # one of them is a statement about the network, not about
            # the link.
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
        the budget. Collection does not block past the budget either: the
        pool is shut down without waiting, so one origin that accepts a
        connection and then dribbles bytes cannot hold the whole lint
        run. Anything not resolved by then counts as unchecked, which is
        what the notice reports.
        """
        workers = max(1, min(concurrency, len(urls)))
        deadline = time.monotonic() + budget if budget > 0 else None

        statuses: Dict[str, Optional[int]] = {}
        unchecked = 0
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {pool.submit(self._probe, url, timeout, deadline): url for url in urls}
            pending = set(futures)
            while pending:
                remaining = None
                if deadline is not None:
                    # A worker already past the deadline is finishing a
                    # request whose own socket timeout bounds it; the
                    # grace keeps that from being counted as unchecked
                    # purely because collection raced it.
                    remaining = max(0.0, deadline - time.monotonic()) + timeout
                done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
                if not done:
                    break  # nothing resolved inside the budget
                for future in done:
                    status, checked = future.result()
                    if checked:
                        statuses[futures[future]] = status
                    else:
                        unchecked += 1
            unchecked += len(pending)
        finally:
            # Never wait: a stuck worker must not extend the run. Its own
            # socket timeout (clamped, and re-clamped per redirect hop)
            # guarantees it ends on its own.
            pool.shutdown(wait=False, cancel_futures=True)
        return statuses, unchecked

    # -- check --------------------------------------------------------------

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        by_url = self._collect(context)
        if not by_url:
            return []

        # Every option here arrives from a repo-controlled `.skillsaw.yaml`,
        # so each is coerced and clamped rather than trusted. A value the
        # clamp cannot make sense of falls back to the default, never to
        # something more permissive than the default.
        timeout = _clamp(_as_float(self.setting("timeout"), 5.0), 0.1, _MAX_TIMEOUT)
        concurrency = _clamp(_as_int(self.setting("concurrency"), 8), 1, _MAX_CONCURRENCY)
        budget = _as_float(self.setting("total-budget"), 30.0)
        if budget < 0:
            # Only the documented 0 disables the cap. A negative budget is
            # a mistake, and must not read as "no limit at all".
            budget = 30.0
        budget = min(budget, _MAX_TOTAL_BUDGET)

        # Sorted so the submission order, and the reported order, are the
        # same for the same repository. Which URLs a short budget reaches
        # still depends on how fast each host answers.
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
            #
            # The count is deliberately NOT in the message. This violation
            # has no file, so baseline identity falls through to hashing
            # rule_id + message (baseline.fingerprint_violation) — and a
            # count that moves with runner latency would give it a new
            # fingerprint every run, so it could never be baselined and
            # would resurface as a new finding under `fail-on: info`. The
            # numbers go to the log, which nothing fingerprints.
            logger.info(
                "%s: %d of %d external URLs unchecked (budget %.1fs exhausted)",
                self.rule_id,
                unchecked,
                len(by_url),
                budget,
            )
            violations.append(
                self.violation(
                    "Some external URLs were left unchecked — the network budget "
                    "was exhausted before every link was probed, so a clean run "
                    "is not proof they all resolve (raise 'total-budget', or run "
                    "with -v for the count)",
                    severity=Severity.INFO,
                    fixable=False,
                    fingerprint_discriminator="network-budget-exhausted",
                )
            )
        return violations


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _as_float(value: Any, fallback: float) -> float:
    """A configured number, or *fallback* when it is not one.

    Config validation warns about a wrong-typed option but still hands
    the value through, so a settings read must not be able to raise out
    of ``check()`` — and a value it cannot use must fall back to the
    default rather than to something more permissive than the default.
    ``nan`` and ``inf`` are rejected for that reason: ``inf`` would mean
    an unbounded socket timeout, which is T13's "hang CI forever".
    """
    if isinstance(value, bool):
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return number


def _as_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return fallback
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _as_list(value: Any, fallback: List[Any]) -> List[Any]:
    """A configured list, or *fallback* when it is not one.

    ``ignore: "https://internal.example.com/"`` — a string where a list
    belongs, and the likeliest YAML mistake here — used to iterate into
    single characters, so ``url.startswith("h")`` matched every http(s)
    URL and the rule silently checked nothing while appearing to run.
    """
    if isinstance(value, list):
        return value
    return list(fallback)
