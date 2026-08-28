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

import collections
import contextlib
import fnmatch
import functools
import ipaddress
import logging
import math
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING, Tuple, TypeVar
from urllib.parse import unquote, urlparse, urlsplit, urlunsplit

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.rules.builtin.content_analysis import gather_all_content_blocks

if TYPE_CHECKING:
    from skillsaw.blocks.base import ContentBlock

logger = logging.getLogger(__name__)

_Number = TypeVar("_Number", int, float)

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
# and azure.microsoft.com does the same on some marketing paths.
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
# `timeout` is a socket timeout, not a per-request one: urllib re-arms it
# on every read, applies it to each address getaddrinfo returns, and hands
# the full value to each redirect hop, so a single worker's worst case is
# roughly methods x hops x addresses x timeout. `total-budget` is
# therefore the bound that matters, and _probe_all enforces it by
# abandoning workers rather than by trusting them to finish.
_MAX_TIMEOUT = 30.0
_MAX_TOTAL_BUDGET = 600.0
_MAX_CONCURRENCY = 32

# The two operands of `_is_ignored`, bounded for the same reason and in
# the same style. It compiles a `.skillsaw.yaml` glob through
# `fnmatch.translate` and matches it against a URL the repository also
# wrote, so both sides of a catastrophically backtracking match are
# attacker-chosen. `fnmatch.translate` gained atomic groups only in
# 3.11 and skillsaw supports 3.9. The SIGALRM budget the banned-
# references rule uses for T13 cannot stand in: `_is_ignored` is
# reached from `_accepts_hop` on worker threads, where signals never
# fire. So the lengths are capped instead — no URL and no ignore
# pattern written on purpose comes near either bound.
_MAX_URL_LENGTH = 2048
_MAX_IGNORE_PATTERN_LENGTH = 256

# Hostnames that are never public, whatever DNS says.
_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

# What `http.client._validate_host` refuses. Checked here as well, so
# the confinement's own reasoning rejects a control character rather
# than depending on a downstream guard to do it — see `_canonical_host`.
_FORBIDDEN_HOST_CHARS = frozenset(chr(code) for code in range(0x21)) | {"\x7f"}

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

    block: "ContentBlock"
    body_line: int
    text: str
    href: str


class _EmptyBody:
    """A response whose body reads as empty, without touching the socket.

    ``HTTPRedirectHandler.http_error_302`` calls ``fp.read()`` on the
    intermediate response before it opens the next hop — a full,
    uncapped read of a body nothing here wants. An origin that answers a
    redirect with an endless chunked stream would be read into the
    worker's memory, bounded only by the per-``recv`` socket timeout.

    Everything except ``read``/``readline`` is forwarded, so ``close()``
    still closes the real response and an ``HTTPError`` built from this
    still behaves like one built from the response itself.
    """

    def __init__(self, response):
        self._response = response

    def read(self, *_args, **_kwargs) -> bytes:
        return b""

    def readline(self, *_args, **_kwargs) -> bytes:
        return b""

    def __getattr__(self, name):
        return getattr(self._response, name)


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

    Two more things the base class does that this one must not: read the
    intermediate body (see :class:`_EmptyBody`), and hand each hop the
    *full* timeout again. ``hop_timeout`` returns what is left of the
    window the caller opened, so a five-hop chain costs one timeout
    rather than five.
    """

    max_redirections = _MAX_REDIRECTS

    def __init__(self, accepts, hop_timeout):
        self._accepts = accepts
        self._hop_timeout = hop_timeout

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self._accepts(newurl):
            raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
        # The base reads req.timeout for the next hop; give it the
        # remainder of the caller's window instead of the full value.
        req.timeout = self._hop_timeout()
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def http_error_302(self, req, fp, code, msg, headers):
        body = _EmptyBody(fp)
        # The base parses the raw ``Location`` header itself before it
        # calls ``redirect_request``, so ``_accepts_hop`` never sees a
        # malformed one and ``urlparse("http://[::1/x")`` would raise
        # straight out of the probe. The header is chosen by the remote
        # party, so that would let any hostile or broken origin turn an
        # opted-in run into a rule-execution-error. Parse it here first
        # and end the chain the way a refused hop does — an
        # ``HTTPError``, which the caller reads as inconclusive.
        #
        # Only the parse is guarded. ``super()`` finishes by calling
        # ``self.parent.open(...)``, which drives the whole remainder of
        # the chain, so wrapping the delegation would convert a bug in
        # this rule into "inconclusive" whenever it happened to be
        # raised below a redirect — while the same bug on a
        # non-redirecting URL surfaced as a rule-execution-error. Which
        # of the two a reader gets is not the remote party's to choose.
        location = headers.get("location") or headers.get("uri")
        if location is not None:
            try:
                urlparse(location)
            except ValueError:
                raise urllib.error.HTTPError(req.full_url, code, msg, headers, body)
        return super().http_error_302(req, body, code, msg, headers)

    # The base aliases these to *its* http_error_302, so overriding one
    # method is not enough — 301 and 307 would keep the uncapped read.
    http_error_301 = http_error_303 = http_error_307 = http_error_302
    if hasattr(urllib.request.HTTPRedirectHandler, "http_error_308"):
        http_error_308 = http_error_302


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
            "description": (
                f"Socket timeout in seconds for one request (clamped to "
                f"0.1-{_MAX_TIMEOUT:g}; a value that is not a finite number "
                "falls back to the default)"
            ),
        },
        "total-budget": {
            "type": "float",
            "default": 30.0,
            "description": (
                "Wall-clock seconds for all requests in a run; remaining URLs "
                f"are left unchecked (clamped to {_MAX_TOTAL_BUDGET:g}; there "
                "is no way to disable the cap — 0 and negatives mean the default)"
            ),
        },
        "concurrency": {
            "type": "int",
            "default": 8,
            "description": (f"Maximum simultaneous requests (clamped to 1-{_MAX_CONCURRENCY})"),
        },
        "ignore": {
            "type": "list",
            "default": [],
            "description": (
                "URL patterns never requested — a glob (fnmatch) when it "
                "contains *, ? or [, otherwise a literal prefix. Matched "
                "against the requested URL, which has no fragment"
            ),
        },
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        allow_private_hosts: bool = False,
    ):
        super().__init__(config)
        # Openers are per-thread (see _opener). The holder is created here,
        # before any worker exists, so no two threads race to create it.
        self._local = threading.local()
        # Admission policy, resolved once. The redirect handler consults
        # it from worker threads, so it must be settled before any
        # request starts — and settling it in the constructor means a
        # direct _probe() call is governed by it too, not only a call
        # that came through check().
        self._ignore = [p for p in _as_list(self.setting("ignore"), []) if isinstance(p, str)]
        # Deliberately NOT a config option. Reaching non-public hosts is
        # the one setting here that is a security boundary rather than a
        # tuning knob, and `.skillsaw.yaml` is written by the same actor
        # T18 defends against — a repo that could set it would disable
        # its own confinement. Only the operator can turn it on, via
        # --allow-private-hosts / SKILLSAW_ALLOW_PRIVATE_HOSTS, which the
        # linter passes here.
        self.allow_private_hosts = bool(allow_private_hosts)

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
    def _canonical_host(host: str) -> Optional[str]:
        """*host* spelled the way the transport will spell it, or None.

        ``urllib.request.Request._parse`` percent-decodes the host, and
        ``socket.getaddrinfo`` hands a ``str`` host to the IDNA codec,
        whose nameprep step applies NFKC normalization and whose label
        splitter treats U+3002, U+FF0E and U+FF61 as dots. Classifying
        the string as authored therefore classifies a host that is never
        the one connected to: ``169%2E254%2E169%2E254``,
        ``169。254。169。254`` and ``１２７.0.0.1`` all reach a numeric
        address, while a confinement reading them verbatim sees names.

        A host the codec refuses is refused here too. That is safe as
        well as simple: ``getaddrinfo`` would raise the same
        ``UnicodeError``, which :data:`_NETWORK_ERRORS` already swallows,
        so such a host could not be fetched anyway.

        Two spellings survive the encoding and are refused after it,
        because both would make the classified string differ from the
        requested one:

        * A leftover ``%``. ``Request._parse`` percent-decodes the host
          it is handed, so a ``%`` that survives *this* decode is
          decoded a second time by urllib, and ``http.client`` then
          splits a decoded ``:`` into a port. Double encoding gets there
          (``%253A``), and so does a single full-width ``％`` (U+FF05),
          which nameprep's NFKC step folds to ``%``. A DNS name or an IP
          literal never legitimately carries one post-decode.
        * A control character. ``str.encode("idna")`` takes a verbatim
          fast path for pure-ASCII labels, checking only their length,
          so ``127.0.0.1%00.evil.com`` arrives intact — a string
          ``inet_aton`` reads as a name and ``getaddrinfo`` truncates at
          the NUL into loopback.
        """
        try:
            canonical = unquote(host).encode("idna").decode("ascii")
        except (UnicodeError, ValueError):
            return None
        if "%" in canonical:
            return None
        if any(char in _FORBIDDEN_HOST_CHARS for char in canonical):
            return None
        return canonical

    @classmethod
    def _canonical_netloc(cls, netloc: str) -> Optional[str]:
        """*netloc* with its host canonicalized — see :meth:`_canonical_host`.

        The port and the IPv6 brackets are carried through untouched;
        only the host is rewritten, so the URL that gets requested,
        matched against ``ignore`` and reported is the one the
        confinement classifies.
        """
        if netloc.startswith("["):
            raw, closed, port = netloc[1:].partition("]")
            if not closed:
                return None
            host = cls._canonical_host(raw)
            return None if host is None else f"[{host}]{port}"
        head, colon, tail = netloc.rpartition(":")
        raw, port = (head, colon + tail) if colon else (tail, "")
        host = cls._canonical_host(raw)
        return None if host is None else f"{host}{port}"

    @classmethod
    def _request_url(cls, href: str) -> Optional[str]:
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
        netloc = cls._canonical_netloc(parts.netloc)
        if netloc is None:
            return None
        # After canonicalization, not before: percent-decoding is what
        # turns ``user%40example.com`` into userinfo, and urllib keeps
        # the whole decoded string as the host it resolves rather than
        # stripping the part in front of the ``@``.
        if "@" in netloc:
            return None
        url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
        if len(url) > _MAX_URL_LENGTH:
            # See _MAX_URL_LENGTH: this is one half of the `ignore`
            # glob's worst case, and the repository writes both halves.
            return None
        return url

    @staticmethod
    def _as_ip_literal(host: str) -> Optional[ipaddress._BaseAddress]:
        """*host* as an IP address if it is a literal in **any** form.

        ``ipaddress`` accepts only dotted-quad and standard IPv6, but the
        resolver is far more liberal: glibc's ``inet_aton`` also takes a
        bare 32-bit integer, octal and hex labels, and short-dotted forms.
        Classifying those as "a name" is how ``http://2852039166/`` — the
        cloud metadata address written as one decimal — walks straight
        past a confinement check that thought it had seen a hostname.

        So the liberal parser gets the final say on what is a literal.
        This still resolves nothing: ``inet_aton`` is pure string
        arithmetic, no lookup.
        """
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            pass
        try:
            return ipaddress.ip_address(socket.inet_ntoa(socket.inet_aton(host)))
        except (OSError, ValueError):
            return None

    @classmethod
    def _is_public_host(cls, netloc: str) -> bool:
        """False when *netloc*'s host is knowably not on the public internet.

        Only IP literals and the reserved local names can be settled
        without a resolver, and this deliberately does not resolve: a
        lookup here would be a network call made before the network gate
        is honoured, and its answer would be stale by the time urllib
        connects anyway (DNS rebinding). So an internal *name* still gets
        through — the honest limits are documented on the rule page, and
        ``--no-network`` is the control that does not depend on parsing.
        """
        # Canonicalize the whole netloc *first*, then take it apart.
        # Classifying the string the transport will resolve rather than
        # the one the repository wrote is the point (see
        # :meth:`_canonical_host`) — and doing it in this order is what
        # makes a delimiter that canonicalization *introduces* get
        # parsed as one, instead of being swallowed into the host and
        # mistaken for a name.
        canonical = cls._canonical_host(netloc.strip())
        if canonical is None:
            return False
        host = canonical.rsplit("@", 1)[-1]
        if host.startswith("["):
            host = host.partition("]")[0][1:]
        elif ":" in host:
            host = host.rsplit(":", 1)[0]
        host = host.rstrip(".").lower()
        if not host:
            return False
        if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
            return False
        address = cls._as_ip_literal(host)
        if address is None:
            # A name. Not resolvable to a verdict here; see the docstring.
            return True
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            address = mapped
        # Two layers, because neither one is a superset of the other.
        # ``is_global`` is False for RFC 6598 CGNAT space (100.64.0.0/10)
        # and for nothing else in ``ipaddress`` — the range Tailscale
        # uses, along with EKS/GKE secondary pod CIDRs and carrier-grade
        # NAT, so it is the private range a runner is most likely to
        # reach that is not 10/8, 172.16/12 or 192.168/16. The explicit
        # predicates in turn catch what ``is_global`` calls global,
        # notably multicast and NAT64. Layered this way, cross-version
        # drift in ``is_global`` can only ever tighten the confinement.
        return not (
            not address.is_global
            or address.is_private
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
            if len(pattern) > _MAX_IGNORE_PATTERN_LENGTH:
                # See _MAX_IGNORE_PATTERN_LENGTH: the other half of the
                # glob's worst case. Skipping the pattern only widens
                # what gets probed, and the confinement still applies.
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
        if not self.allow_private_hosts and not self._is_public_host(urlsplit(url).netloc):
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
    @functools.lru_cache(maxsize=1)
    def _user_agent() -> str:
        """The self-identifying UA, built once rather than per request."""
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
            opener = urllib.request.build_opener(
                _BoundedRedirectHandler(self._accepts_hop, self._hop_timeout)
            )
            opener.addheaders = []
            self._local.opener = opener
        return opener

    def _hop_timeout(self) -> float:
        """What is left of the window the current request opened.

        Read from thread-local state because the opener, and so the
        redirect handler, is per worker thread — see :meth:`_opener`.
        """
        window_ends = getattr(self._local, "window_ends", None)
        if window_ends is None:
            return _MAX_TIMEOUT
        # Never zero: urllib reads a zero timeout as "non-blocking",
        # which fails in a way that has nothing to do with the link.
        return max(0.001, window_ends - time.monotonic())

    def _request(self, url: str, method: str, timeout: float) -> Optional[int]:
        """Status code for one request, or None when nothing was learned.

        No response body is ever read — not the final one, whose context
        manager closes the connection once the status line and headers
        have arrived, and not an intermediate redirect's, which
        :class:`_EmptyBody` keeps urllib from reading.

        ``timeout`` bounds the whole chain, not each hop: it opens a
        window here, and :meth:`_hop_timeout` hands each redirect what is
        left of it.

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
        self._local.window_ends = time.monotonic() + timeout
        try:
            with self._opener().open(request, timeout=timeout) as response:
                return getattr(response, "status", None)
        except urllib.error.HTTPError as exc:
            code = exc.code
            with contextlib.suppress(OSError):
                exc.close()
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

        Deliberately not a :class:`ThreadPoolExecutor`. Its workers are
        non-daemon and ``concurrent.futures.thread`` registers an atexit
        hook that joins every live one, so ``shutdown(wait=False)`` bounds
        only when this function returns — the *process* still blocks at
        interpreter exit. urllib's timeout is per socket operation and is
        re-armed on every read, so an origin that dribbles one byte just
        under it holds a worker open indefinitely, and the exit code is
        never delivered.

        Daemon threads make the bound real: the join has its own deadline,
        and anything still running when it expires is abandoned, counted
        as unchecked, and cannot keep the interpreter alive.
        """
        workers = max(1, min(concurrency, len(urls)))
        deadline = time.monotonic() + budget
        pending = collections.deque(urls)
        results: Dict[str, Tuple[Optional[int], bool]] = {}
        failures: List[BaseException] = []
        lock = threading.Lock()

        def _drain() -> None:
            while True:
                with lock:
                    if not pending or failures:
                        return
                    url = pending.popleft()
                try:
                    outcome = self._probe(url, timeout, deadline)
                except BaseException as exc:  # noqa: BLE001 - re-raised below
                    with lock:
                        failures.append(exc)
                    return
                with lock:
                    results[url] = outcome

        threads = [
            threading.Thread(target=_drain, name="skillsaw-link-probe", daemon=True)
            for _ in range(workers)
        ]
        for thread in threads:
            thread.start()
        # One grace period for the whole join, not one per thread: a
        # worker already past the deadline is finishing a request its own
        # socket timeout bounds, and that should not be counted as
        # unchecked purely because collection raced it.
        join_until = deadline + timeout
        for thread in threads:
            thread.join(timeout=max(0.0, join_until - time.monotonic()))

        with lock:
            if failures:
                # A bug in this rule, not a network condition. Let the
                # linter turn it into an unbaselinable rule-execution-error
                # rather than reporting nothing and exiting 0.
                raise failures[0]
            statuses = {url: status for url, (status, checked) in results.items() if checked}
            unchecked = len(urls) - len(statuses)
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
        # The wall-clock cap has no off switch: 0 and negatives both mean
        # the default. An unbounded budget would be reachable from an
        # untrusted config, which is T13's hang-CI impact with extra steps,
        # so there is deliberately no value that disables it.
        budget = _as_float(self.setting("total-budget"), 30.0)
        if budget <= 0:
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


def _clamp(value: _Number, low: _Number, high: _Number) -> _Number:
    """*value* confined to ``[low, high]``, keeping its type.

    Generic because ``concurrency`` is clamped as an ``int`` and used as
    a thread count, while ``timeout`` is clamped as a ``float``.
    """
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

    Without this, ``ignore: "https://internal.example.com/"`` — a string
    where a list belongs, and the likeliest YAML mistake here — would
    iterate into single characters, so ``url.startswith("h")`` would
    match every http(s) URL and the rule would silently check nothing
    while appearing to run.
    """
    if isinstance(value, list):
        return value
    return list(fallback)
