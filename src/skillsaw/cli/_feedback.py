"""Create local diagnostic bundles for skillsaw bug reports.

The bundle carries skillsaw's own output. Repository files are included
only when the reporter names them with ``--include`` or ``--config``, and
reviewing those for secrets is the reporter's job: skillsaw does not scan
file contents for credentials and does not claim the bundle is sanitized.
Files an ignore file already excludes cannot be bundled at all."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import platform
import re
import secrets
import select
import subprocess
import sys
import sysconfig
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ..config import find_config
from ..discovery.excludes import path_matches_patterns
from ..paths import contained_resolve, safe_exists, safe_is_dir, safe_is_file, safe_resolve
from ._config import _get_version

_ISSUE_URL = "https://github.com/stbenjam/skillsaw/issues/new"
_FEEDBACK_EMAIL = "stephen@bitbin.de"
_GPG_KEY_URL = "https://github.com/stbenjam.gpg"
_BUNDLE_SCHEMA_VERSION = 1
_TERMINAL_ESCAPE = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")


def _safe_terminal_text(data: bytes) -> bytes:
    """Neutralize child diagnostics before writing them to a terminal.

    Escape and control bytes only: a child that emits them could otherwise
    retitle the window or drive the clipboard. This is not a secret scan.
    """
    text = data.decode("utf-8", "replace")
    text = _TERMINAL_ESCAPE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "�", text)
    return text.encode("utf-8", "replace")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle_id(created_at: datetime) -> str:
    return f"skillsaw-feedback-{created_at.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def _archive_path(args, root: Path, bundle_id: str) -> Path | None:
    if args.output is not None:
        output = args.output
        if output.suffix.lower() != ".zip":
            output = output.with_suffix(".zip")
        return safe_resolve(output)
    return root / ".skillsaw-feedback" / f"{bundle_id}.zip"


def _config_path(args, root: Path) -> Path | None:
    if args.config is not None:
        return safe_resolve(args.config)
    return find_config(root)


# Ignore files that mean "keep this out of an artifact that leaves the machine".
# The declaration already exists in the repository and the reporter maintains it,
# so it is the cheap 80% answer to "don't bundle the credentials file" — no
# scanning of file contents, and nothing for skillsaw to keep up to date.
_IGNORE_FILES = (
    ".gitignore",
    ".dockerignore",
    ".npmignore",
    ".helmignore",
    ".gcloudignore",
)


def _ignore_patterns(root: Path) -> list[str]:
    """Patterns from the repository's ignore files, comments and negations dropped."""
    patterns: list[str] = []
    for name in _IGNORE_FILES:
        ignore_file = root / name
        if not safe_is_file(ignore_file):
            continue
        try:
            lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            entry = line.strip()
            # A negation re-includes a path; skipping it keeps this a guardrail
            # that only ever refuses, never grants.
            if not entry or entry.startswith(("#", "!")):
                continue
            entry = entry.rstrip("/")
            if entry:
                patterns.extend((entry, f"{entry}/*", f"**/{entry}", f"**/{entry}/*"))
    return patterns


def _is_ignored(resolved: Path, root: Path, patterns: list[str]) -> bool:
    return path_matches_patterns(resolved, root, patterns)


def _included_file(root: Path, raw_path: str, patterns: list[str]) -> tuple[Path, Path]:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = contained_resolve(candidate, root)
    if resolved is None:
        raise ValueError(f"--include must name a file inside the repository: {raw_path}")
    if not safe_is_file(resolved):
        raise ValueError(f"--include must name a file: {raw_path}")
    if _is_ignored(resolved, root, patterns):
        raise ValueError(
            f"--include refuses a file an ignore file already excludes: {raw_path}. "
            "Copy it to a non-ignored path if you have reviewed it and still want to share it"
        )
    relative = resolved.relative_to(root)
    return resolved, relative


def _run_diagnostic_lint(
    root: Path, config_path: Path | None, *, with_extensions: bool
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "skillsaw",
        "lint",
        "--format",
        "json",
        "--verbose",
        "--no-baseline",
    ]
    if config_path is not None:
        command.extend(["--config", str(config_path)])
    if not with_extensions:
        command.extend(["--no-custom-rules", "--no-plugins"])
    # Never run the child from the repository: ``-m`` puts the process's cwd on
    # ``sys.path[0]``, so a repo carrying a top-level ``skillsaw/`` package would
    # be imported in place of the installed one — arbitrary code execution from
    # repo content, before ``--no-custom-rules``/``--no-plugins`` is even read.
    # The target is passed as a path instead of ``.``.
    command.append(str(root))
    try:
        with tempfile.TemporaryDirectory(prefix="skillsaw-feedback-") as neutral_cwd:
            stdout, stderr, return_code = _run_lint_process(command, Path(neutral_cwd))
        return {
            "command": ["skillsaw", *command[3:-1], "<repository>"],
            "exit_code": return_code,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return {
            "command": ["skillsaw", *command[3:-1], "<repository>"],
            "exit_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
        }


def _lint_child_environment() -> dict[str, str]:
    """Child env that keeps any directory off the interpreter's import path."""
    # Defense in depth beside the neutral cwd: honored on 3.11+, ignored below.
    return {**os.environ, "PYTHONSAFEPATH": "1"}


def _run_lint_process(command: list[str], root: Path) -> tuple[str, str, int]:
    """Run lint, mirroring its interactive verbose output into this terminal."""
    if not sys.stderr.isatty() or os.name == "nt":
        completed = subprocess.run(
            command,
            cwd=root,
            env=_lint_child_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        return completed.stdout, completed.stderr, completed.returncode

    import pty

    master, slave = pty.openpty()
    captured_stderr = bytearray()
    try:
        with tempfile.TemporaryFile(mode="w+b") as stdout_file:
            process = subprocess.Popen(
                command,
                cwd=root,
                env=_lint_child_environment(),
                stdout=stdout_file,
                stderr=slave,
            )
            os.close(slave)
            slave = -1
            deadline = time.monotonic() + 120
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    stdout_file.seek(0)
                    raise subprocess.TimeoutExpired(
                        command, 120, output=stdout_file.read(), stderr=bytes(captured_stderr)
                    )
                readable, _unused, _errors = select.select([master], [], [], min(0.1, remaining))
                if readable:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        # Linux PTYs signal EOF with EIO after the child closes its slave.
                        if error.errno != errno.EIO:
                            raise
                        break
                    if chunk:
                        captured_stderr.extend(chunk)
                        sys.stderr.buffer.write(_safe_terminal_text(chunk))
                        sys.stderr.buffer.flush()
                    elif process.poll() is not None:
                        break
                elif process.poll() is not None:
                    break
            return_code = process.wait(timeout=max(0, deadline - time.monotonic()))
            stdout_file.seek(0)
            stdout = stdout_file.read().decode("utf-8", "replace")
    finally:
        if slave >= 0:
            os.close(slave)
        os.close(master)
    return stdout, captured_stderr.decode("utf-8", "replace"), return_code


def _replace_local_paths(text: str, root: Path, config_path: Path | None) -> str:
    """Keep machine-specific local paths out of text reports.

    The repository root is not enough: the highest-value content in a bundle is
    a traceback, whose frames are interpreter and site-packages paths under the
    operator's home directory, and no credential pattern matches those.
    """
    replacements = [(str(root), "<repository>")] if root != Path(root.anchor) else []
    if config_path is not None:
        replacements.append((str(config_path), "<config>"))
    for path in (sysconfig.get_paths().get("purelib"), sys.prefix, str(Path.home())):
        if path and path not in ("/", ""):
            replacements.append((path, "<venv>" if path != str(Path.home()) else "<home>"))
    # Longest first, so a prefix never shadows the more specific path inside it.
    for needle, marker in sorted(replacements, key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(needle, marker)
    return text


def _issue_url(bundle_name: str, bundle_sha256: str, message: str) -> str:
    body = (
        "### Diagnostic bundle\n\n"
        "Created with `skillsaw feedback`; repository files are omitted unless explicitly "
        "included with `--include` or `--config`. Please attach the generated ZIP to this issue.\n\n"
        f"- Bundle: `{bundle_name}`\n"
        f"- SHA-256: `{bundle_sha256}`\n"
    )
    if message:
        body += f"\n### Reporter note\n\n{message}\n"
    return f"{_ISSUE_URL}?{urlencode({'template': 'bug_report.yml', 'body': body})}"


def _run_feedback(args) -> None:
    if not safe_is_dir(args.path):
        print(f"Error: Path is not a directory: {args.path}", file=sys.stderr)
        sys.exit(1)

    root = safe_resolve(args.path)
    if root is None:
        print(f"Error: Path could not be resolved: {args.path}", file=sys.stderr)
        sys.exit(1)
    config_path = _config_path(args, root)
    if args.config is not None and config_path is None:
        print(f"Error: Config file could not be resolved: {args.config}", file=sys.stderr)
        sys.exit(1)
    if config_path is not None and not safe_is_file(config_path):
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    created_at = datetime.now(timezone.utc)
    bundle_id = _bundle_id(created_at)
    output_path = _archive_path(args, root, bundle_id)
    if output_path is None:
        print(f"Error: Bundle path could not be resolved: {args.output}", file=sys.stderr)
        sys.exit(1)
    if safe_exists(output_path):
        print(f"Error: Bundle already exists: {output_path}", file=sys.stderr)
        sys.exit(1)

    ignore_patterns = _ignore_patterns(root)
    try:
        selected_files = [
            _included_file(root, raw_path, ignore_patterns) for raw_path in args.include
        ]
        if config_path is not None and _is_ignored(config_path, root, ignore_patterns):
            raise ValueError(
                f"--config refuses a file an ignore file already excludes: {config_path}"
            )
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    lint = _run_diagnostic_lint(root, config_path, with_extensions=args.with_extensions)
    artifact_texts: dict[str, str] = {}
    for name, raw_text in (
        ("lint-report.json", lint["stdout"]),
        ("lint-stderr.txt", lint["stderr"]),
    ):
        artifact_texts[name] = _replace_local_paths(raw_text, root, config_path)

    config_included = args.config is not None
    if config_included:
        assert config_path is not None
        try:
            raw_config = config_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            print(f"Error: Could not read config file: {config_path}", file=sys.stderr)
            sys.exit(1)
        artifact_texts["skillsaw-config.yaml"] = raw_config

    included_names = []
    for file_path, relative in selected_files:
        try:
            raw_content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            print(f"Error: Could not read --include file: {relative}", file=sys.stderr)
            sys.exit(1)
        archive_name = f"included/{relative.as_posix()}"
        artifact_texts[archive_name] = raw_content
        included_names.append(relative.as_posix())

    message = args.message
    environment = {
        "bundle_schema_version": _BUNDLE_SCHEMA_VERSION,
        "created_at": created_at.isoformat(),
        "skillsaw_version": _get_version(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "lint_exit_code": lint["exit_code"],
        "lint_timed_out": lint["timed_out"],
        "lint_extensions_enabled": args.with_extensions,
        "config_included": config_included,
        "included_files": included_names,
        "message": message,
    }
    artifact_texts["environment.json"] = json.dumps(environment, indent=2, sort_keys=True) + "\n"

    artifact_bytes = {name: text.encode("utf-8") for name, text in artifact_texts.items()}
    manifest = {
        "bundle_schema_version": _BUNDLE_SCHEMA_VERSION,
        "files": {
            name: {"sha256": _sha256(data), "size_bytes": len(data)}
            for name, data in sorted(artifact_bytes.items())
        },
    }
    artifact_bytes["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    temporary_path = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(f".{output_path.name}.{secrets.token_hex(4)}.tmp")
        descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as archive_file:
            with zipfile.ZipFile(archive_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in sorted(artifact_bytes.items()):
                    archive.writestr(f"{bundle_id}/{name}", data)
        os.link(temporary_path, output_path)
        temporary_path.unlink()
    except (OSError, zipfile.BadZipFile) as error:
        print(f"Error: Could not write diagnostic bundle: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    bundle_sha256 = _sha256(output_path.read_bytes())
    issue_url = _issue_url(output_path.name, bundle_sha256, message)
    result = {
        "bundle": str(output_path),
        "archive_directory": bundle_id,
        "sha256": bundle_sha256,
        "issue_url": issue_url,
        "email": {"to": _FEEDBACK_EMAIL, "gpg_key": _GPG_KEY_URL},
        "included_files": included_names,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("Feedback bundle created")
        print(f"  File:     {output_path}")
        print(f"  Extracts: {bundle_id}/")
        print(f"  SHA-256:  {bundle_sha256}")
        if included_names or config_included:
            print(f"  Your files: {len(included_names) + int(config_included)}")
        print()
        print("Review before sharing")
        if included_names or config_included:
            print("  This bundle contains files you named, copied verbatim. skillsaw does")
            print("  not scan them for secrets. Open the ZIP and check them yourself:")
            if config_included:
                print("    skillsaw-config.yaml")
            for name in included_names:
                print(f"    included/{name}")
        else:
            print("  This bundle contains skillsaw's own output only — no repository files.")
        print()
        print("Share the reviewed bundle")
        print("  GitHub issue:")
        print(f"    {issue_url}")
        print("  Private email:")
        print(f"    Attach it to {_FEEDBACK_EMAIL}")
        print(f"    Optional GPG key: {_GPG_KEY_URL}")
    sys.exit(0)
