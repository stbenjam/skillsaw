"""``--mcp-server`` for ``lint``, ``tree`` and ``pull``: fetch the skills MCP servers serve.

Served skills are Agent Skills, so the ordinary commands read them. What is
wrong with a server rather than a skill — it cannot be reached, it serves files
that disagree with what it advertised — is reported afterwards and fails the run.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

from ..config import find_config
from ..diagnostics import terminal_safe
from ..mcp_skills_pull import (
    PullError,
    ServerTarget,
    command_target,
    config_servers,
    config_target,
    parse_header,
    prepare_output,
    pull,
    url_target,
)
from ..paths import safe_resolve


def _targets(args) -> List[ServerTarget]:
    headers = dict(parse_header(spec) for spec in args.mcp_headers)
    urls = [s for s in args.mcp_servers if s.lower().startswith(("http://", "https://"))]
    if headers and len(urls) != 1:
        # One header set for several hosts would hand each one the others' token.
        raise PullError(
            "--mcp-header applies to a single --mcp-server URL; give several servers "
            "their headers in an MCP config (--mcp-config)"
        )
    targets = [
        url_target(server, headers) if server in urls else command_target(server)
        for server in args.mcp_servers
    ]
    if args.mcp_config:
        servers = config_servers(args.mcp_config)
        base = (safe_resolve(args.mcp_config) or args.mcp_config.absolute()).parent
        for name, entry in servers.items():
            try:
                targets.append(config_target(name, entry, base))
            except PullError as exc:
                # A client config lists every server the user runs; one that
                # cannot be fetched is not a reason to skip the rest.
                print(f"Skipping {terminal_safe(name)}: {terminal_safe(str(exc))}", file=sys.stderr)
    if not targets:
        raise PullError(f"{args.mcp_config} lists no server skillsaw can fetch from")
    return targets


def _announce(target: ServerTarget, out_dir: Optional[Path]) -> None:
    # Only a pull keeps what it fetches, so only a pull says where it went.
    where = "" if out_dir is None else f" into {terminal_safe(str(out_dir / target.label))}/"
    print(f"Fetching skills from {terminal_safe(target.describe())}{where}", file=sys.stderr)


def _summarize(snapshot) -> None:
    """Print one line per server."""
    for server in snapshot["servers"]:
        errors = server["errors"]
        if errors:
            summary = f"{len(server['skills'])} skill(s), {len(errors)} problem(s)"
        elif server["extension"] is None:
            summary = "serves no skills"
        else:
            summary = f"{len(server['skills'])} skill(s)"
        print(f"  {terminal_safe(server['label'])}: {summary}", file=sys.stderr)


def _report_problems(snapshot) -> int:
    """Print every problem the fetch recorded; return how many there were."""
    problems = [
        (server["label"], error) for server in snapshot["servers"] for error in server["errors"]
    ]
    sys.stdout.flush()  # after the lint report, even when stdout is a pipe
    if problems:
        print(f"\n{len(problems)} problem(s) with the servers:", file=sys.stderr)
    for label, error in problems:
        where = f"{error['uri']}: " if error.get("uri") else ""
        print(
            f"  {terminal_safe(label)}: {terminal_safe(where + error['message'])}", file=sys.stderr
        )
    return len(problems)


def _fetch(args, out_dir: Path, kept: bool):
    """Pull every server's skills into *out_dir*; exit 1 when the pull cannot start."""
    try:
        targets = _targets(args)
        prepare_output(out_dir)
        snapshot = pull(
            targets,
            out_dir,
            timeout=args.mcp_timeout,
            max_skills=args.mcp_max_skills,
            max_bytes=args.mcp_max_bytes,
            progress=lambda target: _announce(target, out_dir if kept else None),
        )
    except PullError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    _summarize(snapshot)
    return snapshot


def _run_pull(args) -> None:
    """Fetch what the servers serve into ``--output`` without linting it."""
    snapshot = _fetch(args, args.output, kept=True)
    sys.exit(1 if _report_problems(snapshot) else 0)


@contextmanager
def _fetched(args):
    """Fetch what the servers serve into a temporary directory, removed afterwards.

    The configuration is the one the command would use in the current
    directory, so rule settings and severity overrides apply.
    """
    if args.config is None:
        args.config = find_config(Path.cwd())
    args.scratch_paths = True  # never discover a config or baseline from the scratch path
    scratch = Path(tempfile.mkdtemp(prefix="skillsaw-"))
    try:
        out_dir = scratch / "mcp-skills"
        yield out_dir, _fetch(args, out_dir, kept=False)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _finish(snapshot, run) -> None:
    """Run the command, then list the servers' problems; any of them fails the run."""
    print(file=sys.stderr)
    try:
        run()
        status = 0
    except SystemExit as exc:
        status = exc.code if isinstance(exc.code, int) else int(bool(exc.code))
    if _report_problems(snapshot):
        status = status or 1
    sys.exit(status)


def _run_lint_mcp_skills(args) -> None:
    from ._lint import _run_lint

    with _fetched(args) as (out_dir, snapshot):
        args.path = [out_dir]
        _finish(snapshot, lambda: _run_lint(args))


def _run_tree_mcp_skills(args) -> None:
    from ._tree import _run_tree

    with _fetched(args) as (out_dir, snapshot):
        args.path = out_dir
        _finish(snapshot, lambda: _run_tree(args))
