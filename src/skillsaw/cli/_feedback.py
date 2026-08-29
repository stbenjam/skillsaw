"""Create local diagnostic bundles for skillsaw bug reports.

The bundle carries skillsaw's own output. Repository files are included
only when the reporter names them with ``--include`` or ``--config``, and
reviewing those for secrets is the reporter's job: skillsaw does not scan
file contents for credentials and does not claim the bundle is sanitized.
A file whose name means credentials (``.env``, ``id_rsa``, ``*.pem``) or that
an ignore file already excludes cannot be bundled at all."""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import io
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
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ..config import find_config
from ..paths import contained_resolve, safe_exists, safe_is_dir, safe_is_file, safe_resolve
from ..utils import mkdir_parents_anchored, read_text, write_bytes_atomic
from ._config import _get_version

_ISSUE_URL = "https://github.com/stbenjam/skillsaw/issues/new"
_FEEDBACK_EMAIL = "stephen@bitbin.de"
_GPG_KEY_URL = "https://github.com/stbenjam.gpg"
_BUNDLE_SCHEMA_VERSION = 1
_LINT_TIMEOUT_SECONDS = 120
_TERMINAL_ESCAPE = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _neutralize_terminal_control(text: str) -> str:
    """Strip escape and control bytes from child diagnostics.

    A child that emits them could otherwise retitle the window or drive the
    clipboard \u2014 of whoever displays the text, which is the reporter for the
    live mirror and the maintainer who ``cat``s the archived copy. Both get the
    same treatment. This is not a secret scan.
    """
    text = _TERMINAL_ESCAPE.sub("", text)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "\ufffd", text)


def _safe_terminal_text(data: bytes) -> bytes:
    """The bytes-level mirror of :func:`_neutralize_terminal_control`."""
    return _neutralize_terminal_control(data.decode("utf-8", "replace")).encode("utf-8", "replace")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle_id(created_at: datetime) -> str:
    return f"skillsaw-feedback-{created_at.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def _archive_path(args, root: Path, bundle_id: str) -> Path | None:
    if args.output is not None:
        output = args.output
        if output.suffix.lower() != ".zip":
            # Append rather than with_suffix, which replaces: `bundle.tar.gz`
            # must become `bundle.tar.gz.zip`, never `bundle.tar.zip`.
            output = output.with_name(output.name + ".zip")
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


# Files whose *name* is the declaration: they exist to hold credentials, so a
# reporter naming one is almost always an accident. This is a fixed list of
# names, never a scan of contents — when it is wrong the fix is one more entry,
# not a pattern that has to be re-tuned against everything it already matched.
_SECRET_FILENAMES = frozenset(
    {
        ".env",
        ".netrc",
        "_netrc",
        ".npmrc",
        ".pypirc",
        ".pgpass",
        ".htpasswd",
        ".git-credentials",
        "credentials",
        "credentials.json",
        "kubeconfig",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "secrets.yaml",
        "secrets.yml",
        "terraform.tfvars",
    }
)
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".tfvars")
# ``.env.example`` and friends are written to be shared; ``.env.production`` is not.
_SHAREABLE_VARIANTS = (".example", ".sample", ".template", ".dist", ".defaults")


def _is_secret_filename(name: str) -> bool:
    """Whether a file's name alone marks it as credential storage."""
    lowered = name.lower()
    if lowered.endswith(_SHAREABLE_VARIANTS) or lowered.endswith(".pub"):
        return False
    if lowered in _SECRET_FILENAMES or lowered.endswith(_SECRET_SUFFIXES):
        return True
    # ``.env.production``, ``.env.local`` — but not a file merely ending in ".env".
    return lowered.startswith(".env.")


@dataclass(frozen=True)
class _IgnorePattern:
    value: str
    anchored: bool
    directory_only: bool
    ignore_case: bool


def _git_ignore_case(root: Path) -> bool:
    """Return Git's case-folding policy without requiring the repository API."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "config", "--bool", "core.ignoreCase"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return os.path.normcase("A") == os.path.normcase("a")
    if completed.returncode == 0:
        return completed.stdout.strip().lower() == "true"
    return os.path.normcase("A") == os.path.normcase("a")


def _ignore_patterns(root: Path) -> list[_IgnorePattern]:
    """Patterns from the repository's ignore files, comments and negations dropped."""
    patterns: list[_IgnorePattern] = []
    for name in _IGNORE_FILES:
        ignore_file = root / name
        if not safe_is_file(ignore_file):
            continue
        content = read_text(ignore_file)
        if content is None:
            continue
        ignore_case = _git_ignore_case(root) if name == ".gitignore" else os.name == "nt"
        for line in content.splitlines():
            entry = line.strip()
            # A negation re-includes a path; skipping it keeps this a guardrail
            # that only ever refuses, never grants.
            if not entry or entry.startswith(("#", "!")):
                continue
            directory_only = entry.endswith("/")
            entry = entry.rstrip("/")
            if entry:
                anchored = entry.startswith("/") or "/" in entry
                value = entry.lstrip("/")
                if value:
                    patterns.append(_IgnorePattern(value, anchored, directory_only, ignore_case))
    return patterns


def _path_pattern_matches(path_parts: tuple[str, ...], pattern_parts: tuple[str, ...]) -> bool:
    """Match a gitignore path pattern without allowing ``*`` to cross ``/``."""

    @lru_cache(maxsize=None)
    def match(pattern_index: int, path_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        pattern = pattern_parts[pattern_index]
        if pattern == "**":
            if pattern_index == len(pattern_parts) - 1:
                # A trailing '/**' means contents of the directory, not the
                # directory entry (or an identically named regular file).
                return path_index < len(path_parts)
            return match(pattern_index + 1, path_index) or (
                path_index < len(path_parts) and match(pattern_index, path_index + 1)
            )
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], pattern)
            and match(pattern_index + 1, path_index + 1)
        )

    return match(0, 0)


def _ignore_pattern_matches(path_parts: tuple[str, ...], pattern: _IgnorePattern) -> bool:
    pattern_value = pattern.value.translate(_ASCII_LOWER) if pattern.ignore_case else pattern.value
    comparable_parts = (
        tuple(part.translate(_ASCII_LOWER) for part in path_parts)
        if pattern.ignore_case
        else path_parts
    )
    eligible_parts = path_parts[:-1] if pattern.directory_only else path_parts
    comparable_eligible_parts = (
        comparable_parts[:-1] if pattern.directory_only else comparable_parts
    )
    pattern_parts = tuple(pattern_value.split("/"))
    if not pattern.anchored:
        return any(fnmatch.fnmatchcase(part, pattern_value) for part in comparable_eligible_parts)
    return any(
        _path_pattern_matches(comparable_parts[:end], pattern_parts)
        for end in range(1, len(eligible_parts) + 1)
    )


def _is_ignored(resolved: Path, root: Path, patterns: list[_IgnorePattern]) -> bool:
    try:
        path_parts = resolved.relative_to(root).parts
    except ValueError:
        return False
    return any(_ignore_pattern_matches(path_parts, pattern) for pattern in patterns)


def _included_file(root: Path, raw_path: str, patterns: list[_IgnorePattern]) -> tuple[Path, Path]:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = contained_resolve(candidate, root)
    if resolved is None:
        raise ValueError(f"--include must name a file inside the repository: {raw_path}")
    if not safe_is_file(resolved):
        raise ValueError(f"--include must name a file: {raw_path}")
    if _is_secret_filename(resolved.name):
        raise ValueError(
            f"--include refuses {resolved.name}: files with this name hold credentials. "
            "Put just the part you need to demonstrate the bug in another file"
        )
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
            timeout=_LINT_TIMEOUT_SECONDS,
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
            deadline = time.monotonic() + _LINT_TIMEOUT_SECONDS
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    stdout_file.seek(0)
                    raise subprocess.TimeoutExpired(
                        command,
                        _LINT_TIMEOUT_SECONDS,
                        output=stdout_file.read(),
                        stderr=bytes(captured_stderr),
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
        if config_path is not None and _is_secret_filename(config_path.name):
            raise ValueError(f"--config refuses {config_path.name}: that name holds credentials")
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
        artifact_texts[name] = _neutralize_terminal_control(
            _replace_local_paths(raw_text, root, config_path)
        )

    config_included = args.config is not None
    if config_included:
        assert config_path is not None
        raw_config = read_text(config_path)
        if raw_config is None:
            print(f"Error: Could not read config file: {config_path}", file=sys.stderr)
            sys.exit(1)
        artifact_texts["skillsaw-config.yaml"] = raw_config

    included_names = []
    included_bytes: dict[str, bytes] = {}
    for file_path, relative in selected_files:
        try:
            raw_content = file_path.read_bytes()
            raw_content.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            print(f"Error: Could not read --include file: {relative}", file=sys.stderr)
            sys.exit(1)
        included_bytes[f"included/{relative.as_posix()}"] = raw_content
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
    artifact_bytes.update(included_bytes)
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

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(artifact_bytes.items()):
            archive.writestr(f"{bundle_id}/{name}", data)
    archive_bytes = buffer.getvalue()
    # Anchor to the repository whenever the bundle lands inside it — the default
    # path does. Both helpers then refuse to create or write through a symlinked
    # parent, which a bare mkdir would happily follow out of the tree.
    anchored = output_path.is_relative_to(root)
    try:
        if anchored:
            mkdir_parents_anchored(output_path.parent, root=root)
            write_bytes_atomic(output_path, archive_bytes, root=root)
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_bytes_atomic(output_path, archive_bytes)
    except (OSError, zipfile.BadZipFile) as error:
        print(f"Error: Could not write diagnostic bundle: {error}", file=sys.stderr)
        sys.exit(1)

    bundle_sha256 = _sha256(archive_bytes)
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
